/* Running-server provenance and the version frozen into this browser page.
 * Reading status never restarts a server or reloads an editor automatically. The build line (version, Check for
 * updates, Last checked) is on the Settings page (settings.js), an admin's; a member sees the warning box under
 * the top bar when something needs doing, never the hashes. The footer is one quiet line: the prices' date and
 * the exchange rate.
 * Also the simulations setting (GET/PUT /api/simulations, lib/api/simulations.py), checked with the
 * version: beside each Forge run control (a button marked data-run), why the visitor can't start a run
 * now (simulationsGate), and on the Settings page an admin's control (who may start runs, and how many Forge
 * workers the PC uses at once). Nothing is said across the page. And the database's state (/api/status's
 * "database", lib/dbstatus.py): a warning when it can't be used. */
"use strict";

const VERSION_POLL_MS = 30000;
const PAGE_WEB_REVISION = document.querySelector('meta[name="decklab-web-revision"]')?.content || null;
let versionTimer = null, versionRequest = null, versionMonitoring = false;
let versionHidden = false, versionWarning = null;

function versionInfo(build, pageRevision) {
  if (!build) {
    const messages = ["This server can't report its version. Restart Deck Lab on the PC, then reload this page."];
    return { label: "Server version unavailable", messages, reload: false, forEveryone: messages };
  }
  const commit = (sha, dirty) => (sha ? sha.slice(0, 8) : "unknown") + (dirty ? " + local changes" : "");
  let label = `Server ${commit(build.running_commit, build.running_dirty)} · Checkout ${commit(build.latest_commit, build.latest_dirty)}`;
  const messages = [];
  const reload = Boolean(pageRevision && pageRevision !== "unknown" && !pageRevision.startsWith("__")
    && build.web_revision && pageRevision !== build.web_revision);
  if (build.restart_required === true) {
    label += " · Restart needed";
    messages.push("The server code has changed since Deck Lab started. Restart Deck Lab on the PC to load the changes.");
  }
  if (reload) messages.push("This browser page is out of date. Reload it to use the latest page files.");
  if (build.error || build.restart_required == null) {
    label += " · Version not verified";
    messages.push("The running version couldn't be fully checked. " + (build.error || "Startup information isn't available."));
  } else if (!build.restart_required) {
    label += reload ? " · Reload page" : " · Server code current";
  }
  // What only an admin can act on (the PC's code): a member is told only to restart or reload (forEveryone).
  const forEveryone = [...messages];
  if (build.error || build.restart_required == null) forEveryone.pop();
  if (build.running_dirty) messages.push("The server started with uncommitted application changes; its commit ID alone doesn't identify all the running code.");
  return { label, messages, reload, forEveryone };
}

/** The footer's lines about the database. Everyone is told when it can't be used; an admin (the only one
 * the server sends the details to) also why, when migrations are waiting (and whether the stores work
 * meanwhile: db.usable), when the check itself failed, when the last backup that worked is older than
 * the server's limit (config.json's stale_backup_hours), and, once the inventory lives in the database
 * (db.inventory), when the pages show a stale copy of it or there's nothing imported to show. */
function databaseMessages(db) {
  if (!db || db.ok == null) return [];        // not checked yet (the server has just started)
  const out = [];
  if (db.ok === false) {
    if (db.error === "migrations pending") {
      const n = db.pending_migrations;
      out.push((n ? `Deck Lab's database has ${n} migration${n === 1 ? "" : "s"} waiting.` :
        "Deck Lab's database migrations need attention.") +
        " Run python -m decklab.db migrate on the PC (decklab/data/logs/db.log says more)." +
        (db.usable === false ? " Until then, wishlists, settings and play records can't be read or saved." : ""));
    } else if (db.error === "check failed") {
      out.push("Deck Lab couldn't check its database just now; decklab/data/logs/db.log on the PC says why. " +
        "It checks again in a minute.");
    } else {
      out.push("Deck Lab's database isn't reachable, so wishlists, settings and play records can't be " +
        "read or saved right now. Try again in a minute.");
      if (db.error === "psycopg missing") out.push("The server's Python can't use the database: " +
        (db.venv || "psycopg isn't installed for it") + ".");
    }
  }
  const inv = db.inventory;
  if (inv && inv.stale) {
    out.push("The collection, decks, orders, products, watchlist and accessories are read from the database, " +
      "which can't be used right now: the pages show them as they were when it was last reached, and changes to " +
      "them can't be saved.");
  } else if (inv && inv.not_imported) {
    out.push("Deck Lab's database holds no inventory. Restore the newest backup into it on the PC, then check " +
      "it with python -m decklab.db status.");
  }
  if (db.backup_stale) {
    const hours = db.stale_hours ? ` (more than ${db.stale_hours} hours ago)` : "";
    out.push(db.last_backup ?
      `The last database backup that worked was on ${new Date(db.last_backup).toLocaleString("en-AU")}${hours}. ` +
        "Check the nightly task: python -m decklab.db schedule status." :
      "No database backup has worked yet. Run python -m decklab.db backup on the PC.");
  }
  if (db.checks_warning) out.push(db.checks_warning);   // the nightly checks, worded by lib/dbstatus.py
  return out;
}

/** Fetch a fresh HTML address while retaining the route and page options. Navigation uses
 * the editor's normal beforeunload guard, and does not clear profiles, drafts or preferences. */
function reloadDeckLab() {
  const url = new URL(window.location.href);
  url.searchParams.set("v", Date.now().toString(36));
  window.location.assign(url.href);
}

/** restart: a home admin may restart Deck Lab from Settings (settings-restart.js), so the box links there. */
function showVersionWarning(messages, reload = false, database = [], restart = false) {
  const signature = JSON.stringify([messages, reload, database, restart]);
  if (signature === versionWarning) return;
  versionWarning = signature;
  const host = clear($("#build-warning"));
  host.hidden = !messages.length && !database.length;
  if (database.length) host.append(el("h2", { class: "box-head", text: "Deck Lab's database" }),
    ...database.map((text) => el("p", { text })));
  if (!messages.length) return;
  host.append(el("h2", { class: "box-head", text: "Deck Lab version" }),
    ...messages.map((text) => el("p", { text })));
  if (reload) host.append(el("button", { type: "button", class: "btn", text: "Reload page",
    // The editor's existing beforeunload guard protects unsaved work.
    onclick: reloadDeckLab }));
  if (restart) host.append(el("a", { class: "btn btn-secondary", href: "#/settings?part=about", text: "Restart Deck Lab…" }));
}

/** Whether the footer shows the build line (version, Check for updates, Last checked): not to a member. */
function showsBuildLine() {
  return !(state.profile && state.profile.role === "member");
}

/** Show a /api/status answer: the warning box (everyone), the Settings page's build line and card data (when
 * it's on screen), and the footer's one line. Kept in state.status for the Settings page drawn later. */
function renderVersionStatus(s) {
  state.status = s;
  const view = versionInfo(s.build, PAGE_WEB_REVISION);
  const buildLine = showsBuildLine();
  const line = document.querySelector(".build-footer");
  if (line) line.hidden = !buildLine;
  const checked = $("#build-checked"), version = $("#build-version");
  if (checked) {
    checked.hidden = !buildLine;
    checked.textContent = `Last checked ${new Date().toLocaleTimeString("en-AU")}.`;
  }
  if (version) version.textContent = view.label;
  showVersionWarning(buildLine ? view.messages : view.forEveryone, view.reload, databaseMessages(s.database),
    s.build?.restart_required === true && typeof mayRestartServer === "function" && mayRestartServer());
  const cards = $("#settings-cards");
  const cardWords = s.cards?.ready
    ? `Card data from Scryfall, index built ${(s.cards.built_at || "").slice(0, 10)}` +
      (s.cards.price_date ? `, prices of ${s.cards.price_date}` : "") + (s.fx ? `. 1 USD = ${s.fx.rate} AUD (ECB rate of ${s.fx.date})` : "") + "."
    : s.updating ? "Card data is being downloaded from Scryfall…" : "No card data yet. Deck Lab downloads it from Scryfall when it starts.";
  // A status region: rewritten only when the words change, so it announces the download starting and finishing,
  // not every check.
  if (cards && cards.textContent !== cardWords) cards.textContent = cardWords;
  const footer = $("#footer-data");
  if (footer) footer.textContent = footerLine(s);
}

/** The footer's one quiet line: "Prices 2026-10-12 · 1 USD = 1.4237 AUD", or what the card data is doing. */
function footerLine(s) {
  const parts = [];
  if (s.cards?.ready) { if (s.cards.price_date) parts.push(`Prices ${s.cards.price_date}`); }
  else parts.push(s.updating ? "Card data is downloading from Scryfall" : "No card data yet");
  if (s.fx) parts.push(`1 USD = ${s.fx.rate} AUD`);
  return parts.join(" · ");
}

/** Also called after the card-data loading screen completes. One request/timer serves every page. */
async function showFooter() {
  clearTimeout(versionTimer);
  if (versionRequest) return versionRequest;
  if (versionHidden || document.visibilityState === "hidden") return;
  const button = $("#build-check");
  if (button) button.disabled = true;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10000);
  versionRequest = (async () => {
    try {
      renderVersionStatus(await api("/api/status", { signal: controller.signal }));
      loadSimulations();
    } catch (error) {
      const version = $("#build-version");
      if (version) version.textContent = "Version check unavailable";
      showVersionWarning(["Can't check whether Deck Lab is up to date. " + error.message]);
    } finally {
      clearTimeout(timeout);
      versionRequest = null;
      const again = $("#build-check");       // the Settings page may have been drawn meanwhile
      if (again) again.disabled = false;
      if (versionMonitoring && !versionHidden && document.visibilityState !== "hidden") {
        versionTimer = setTimeout(showFooter, VERSION_POLL_MS);
      }
    }
  })();
  return versionRequest;
}

function startVersionMonitor() {
  if (versionMonitoring) return;
  versionMonitoring = true;
  watchRunControls();
  const check = $("#build-check");          // the Settings page's (it wires its own when it's drawn later)
  if (check) check.addEventListener("click", showFooter);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") clearTimeout(versionTimer);
    else showFooter();
  });
  window.addEventListener("focus", showFooter);
  window.addEventListener("online", showFooter);
  window.addEventListener("pagehide", () => { versionHidden = true; clearTimeout(versionTimer); });
  window.addEventListener("pageshow", () => { versionHidden = false; showFooter(); });
  showFooter();
}

// ------------------------------------------------------------- the simulations setting

const SIM_WORKER_CHOICES = [12, 8, 6, 4, 2, 1];
let simRequest = null;

/** GET /api/simulations for the profile chosen, then the notice and the footer control. Errors leave both as
 * they were (the server still refuses what the setting doesn't allow). */
async function loadSimulations() {
  if (!state.profile || simRequest) return simRequest;
  simRequest = (async () => {
    try {
      renderSimulations(await api("/api/simulations"));
      state.simulationsError = null;
    } catch (e) {
      /* the footer's version check says when the server can't be reached; the Settings page says it in its part */
      state.simulationsError = e;
    } finally {
      simRequest = null;
    }
  })();
  return simRequest;
}

/** Keep a /api/simulations answer, bring the run controls up to date with it, and show an admin's setting on
 * the Settings page when it's on screen. Matchups also has a neutral mode chip; a member is told beside each Play
 * or Start (syncRunControls), and so is an admin while runs are paused. */
function renderSimulations(s) {
  state.simulations = s;
  syncSimulationsChips();
  syncRunControls();
  if (typeof syncEditorForgeSummary === "function") syncEditorForgeSummary();
  const loading = $("#sim-loading");
  if (loading) loading.hidden = true;
  const box = $("#sim-settings");
  if (!box) return;
  box.hidden = !s.may_edit;
  if (!s.may_edit) return;
  const mode = $("#sim-mode");
  if (mode) {
    mode.value = s.mode;
    for (const button of mode.querySelectorAll("[data-mode]")) {
      button.setAttribute("aria-pressed", String(button.dataset.mode === s.mode));
    }
  }
  const workers = $("#sim-workers");
  if (workers) {
    const choices = [s.max_workers, ...SIM_WORKER_CHOICES.filter((n) => n < s.max_workers)];
    if (s.workers && !choices.includes(s.workers)) choices.push(s.workers);
    clear(workers).append(...choices.sort((a, b) => b - a).map((n) =>
      el("option", { value: String(n), text: n === s.max_workers ? `All ${n}` : String(n) })));
    workers.value = String(s.workers || s.max_workers);
    workers.dataset.max = String(s.max_workers);
  }
  const since = s.by ? `Set by ${s.by}${s.since ? ` on ${new Date(s.since).toLocaleString("en-AU")}` : ""}.` : "";
  // The database couldn't be read: the server goes by the last setting it knew (or the default).
  const unavailable = s.unavailable ? " The database isn't reachable, so this may not be the saved setting." : "";
  const sinceLine = $("#sim-since");
  if (sinceLine) sinceLine.textContent = (since + unavailable).trim();
}

/** Whether the viewer may start a Forge run now, and if not why: {may, why} from GET /api/simulations'
 * may_start and why_not ("Only an admin can start simulations right now. Saved results still show.": it names
 * nobody, E10-S34). It may until
 * that's known, as the server checks every start anyway. Pages show why beside a disabled Play or Start. */
function simulationsGate() {
  const s = state.simulations;
  if (!s || s.may_start !== false) return { may: true, why: null };
  return { may: false, why: (s.why_not || "Simulations can't be started right now.") +
    (s.unavailable ? " The database isn't reachable, so this may not be the saved setting." : "") };
}

/** Whether the viewer may start a Forge run now (GET /api/simulations; yes until it's known, as the server
 * checks every start anyway). */
function mayStartRuns() {
  return simulationsGate().may;
}

/** Forge's run controls (a Play or Start button marked data-run): while the viewer may not start a run, each
 * is disabled with a line under its row saying why ("Only an admin can start simulations right now."). When they
 * may again, the button goes back to how its page left it. Pages call it after drawing a control; a
 * MutationObserver (watchRunControls) catches the ones drawn later. */
function syncRunControls(root = document) {
  if (!root || typeof root.querySelectorAll !== "function") return;
  const gate = simulationsGate();
  const blocked = !gate.may, why = gate.why || "";
  const buttons = root.matches && root.matches("[data-run]") ? [root] : [...root.querySelectorAll("[data-run]")];
  for (const button of buttons) {
    const host = button.closest(".actions") || button;
    const next = host.nextElementSibling;
    let note = next && next.classList.contains("run-blocked") ? next : null;
    if (blocked) {
      if (button.dataset.runBlocked === undefined) {
        button.dataset.runBlocked = String(button.disabled);
        button.disabled = true;
      }
      if (!note) {
        note = el("p", { class: "run-blocked" });
        host.after(note);
      }
      note.textContent = why;
    } else {
      if (button.dataset.runBlocked !== undefined) {
        button.disabled = button.dataset.runBlocked === "true";
        delete button.dataset.runBlocked;
      }
      if (note) note.remove();
    }
  }
}

/** Run controls drawn after the simulations answer came (a page, a poll's redraw) get the same treatment. */
function watchRunControls() {
  if (typeof MutationObserver !== "function") return;
  new MutationObserver((records) => {
    if (mayStartRuns()) return;
    for (const record of records) {
      for (const node of record.addedNodes) if (node.nodeType === 1) syncRunControls(node);
    }
  }).observe(document.body, { childList: true, subtree: true });
}

async function changeSimulations(change) {
  try {
    renderSimulations(await apiWrite("/api/simulations", { profile: state.profile && state.profile.id, ...change }, "PUT"));
    toast("Simulations setting saved.");
  } catch (e) {
    toast(`The simulations setting couldn't be saved: ${e.message}`);
    loadSimulations();
  }
}


/** Matchups' neutral, read-only setting chip. An unknown answer supplies no guessed mode. */
function simulationsChip() {
  const chip = el("span", { class: "chip chip-plain simulations-chip", role: "img", "data-simulations-chip": "" });
  drawSimulationsChip(chip);
  return chip;
}

function drawSimulationsChip(chip) {
  const setting = state.simulations;
  const mode = new Map([["admins", "Admins only"], ["everyone", "Anyone"], ["paused", "Paused"]]).get(setting?.mode);
  const words = mode ? `Simulations: ${mode}` : "";
  chip.hidden = !words;
  chip.textContent = words;
  chip.setAttribute("aria-label", words);
  if (setting?.unavailable) chip.setAttribute("title", "The database isn't reachable; this is the server's current fallback setting.");
  else chip.removeAttribute("title");
}

function syncSimulationsChips() {
  for (const chip of document.querySelectorAll("[data-simulations-chip]")) drawSimulationsChip(chip);
}
