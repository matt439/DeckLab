/* Deck Lab's page: Settings (#/settings, decklab/UI-REVIEW.md 2.2), an admin's page. Who may start Forge
simulations and how many Forge workers the PC uses (GET/PUT /api/simulations, lib/api/simulations.py), Visits
(GET /api/visits, lib/api/visits.py: who has used Deck Lab, when, and the pages they opened), database-maintenance
history (GET /api/settings/maintenance, lib/api/maintenance.py; reading runs no jobs), and About Deck Lab:
the running server's version, Check for updates, the card data and Restart Deck Lab (settings-restart.js). These used to sit in every page's footer;
the footer is now one quiet line (version.js).

The parts carry the ids version.js fills (renderSimulations, renderVersionStatus): #sim-settings, #sim-mode
(a segmented switch of [data-mode] buttons), #sim-workers, #sim-since; #visits-list (renderVisits); .build-footer
with #build-version and #build-check, #build-checked and #settings-cards. A member who opens the address is told
it's for admins.

Loaded after version.js and before app.js, whose route() calls showSettings(). Nothing here runs at load.
*/
"use strict";

const SIM_MODE_WORDS = [["admins", "Only admins"], ["everyone", "Anyone"], ["paused", "Paused"]];

function showSettings(params, token) {
  setTitle("Settings");
  const main = clear($("#main"));
  if (!isAdminProfile()) {
    add(main, [pageHead({ title: routeH1("settings") }),
      el("div", { class: "box box-info" },
        el("p", { text: "Deck Lab's settings are for admins. Your theme is in the menu under your initial, top right." }))]);
    afterRender();
    return;
  }
  const mode = el("div", { class: "segmented", id: "sim-mode", role: "group", "aria-labelledby": "sim-mode-label" },
    SIM_MODE_WORDS.map(([value, text]) => el("button", { type: "button", "data-mode": value, "aria-pressed": "false", text,
      onclick: () => changeSimulations({ mode: value }) })));
  const workers = el("select", { id: "sim-workers", style: "max-width: 320px", onchange: (event) => {   // not panel-wide on QHD
    const n = Number(event.target.value);
    changeSimulations({ workers: n >= Number(event.target.dataset.max) ? null : n });
  } });
  const check = el("button", { type: "button", class: "btn btn-secondary", id: "build-check", text: "Check for updates",
    onclick: () => showFooter() });
  add(main, [pageHead({ title: routeH1("settings"),
      description: "Settings for everyone who uses Deck Lab. Only admins see this page." }),
    el("div", { class: "settings-parts" },
      el("section", { class: "panel settings-part", id: "settings-simulations", "aria-labelledby": "settings-sim-title" },
        el("h2", { id: "settings-sim-title", text: "Simulations" }),
        el("p", { class: "sub", text: "Forge plays matchups and tests changes on the PC. Saved results always show." }),
        el("div", { class: "settings-fields", id: "sim-settings" },
          el("div", { class: "field" }, el("span", { id: "sim-mode-label", text: "Who can start them" }), mode),
          el("label", { class: "field", for: "sim-workers" }, el("span", { text: "Forge workers at once" }), workers),
          el("p", { class: "sub", id: "sim-since" })),
        el("div", { id: "sim-loading" }, loadingBox("Loading the simulations setting…", { small: true }))),
      commanderNightSettings(),
      settingsMembersPanel(),
      settingsMaintenancePanel(token),
      el("section", { class: "panel settings-part", id: "settings-visits", "aria-labelledby": "settings-visits-title" },
        el("h2", { id: "settings-visits-title", text: "Visits" }),
        el("p", { class: "sub", text: `Who has opened Deck Lab, and which pages. The last ${VISIT_DAYS} days unless it says otherwise.` }),
        el("div", { class: "visits-list", id: "visits-list" }, loadingBox("Loading visits…", { small: true }))),
      el("section", { class: "panel settings-part", id: "settings-about", "aria-labelledby": "settings-about-title" },
        el("h2", { id: "settings-about-title", text: "About Deck Lab" }),
        // Not a live region: the version line is rewritten on every check. The spinner goes with the first answer.
        el("div", { class: "build-footer" }, el("span", { id: "build-version" },
          el("span", { class: "spinner spinner-small", "aria-hidden": "true" }), " Checking the version…")),
        el("p", { class: "sub", id: "build-checked" }),
        el("p", { class: "sub", id: "settings-cards", role: "status" }),
        el("div", { class: "actions" }, check),
        settingsRestartPart()))]);
  byId("sim-settings").hidden = true;
  afterRender();
  if (params && params.get("part") === "about") {
    const about = byId("settings-about");
    if (about && about.scrollIntoView) about.scrollIntoView();
  }
  if (state.simulations) renderSimulations(state.simulations);
  if (state.status) renderVersionStatus(state.status);
  settingsSimulations(token);
  loadCommanderNightSettings(token);
  loadSettingsMembers(token);
  loadSettingsMaintenance(token);
  loadVisits(token);
  loadServerRestart(token);
  showFooter();
}

// ------------------------------------------------------- maintenance history

const MAINTENANCE_JOBS = [["dump", "Backup"], ["export", "Export"], ["check", "Integrity check"], ["restore_check", "Restore check"]];
const MAINTENANCE_HEALTH = { success: "Succeeded", failure: "Failed", stale: "Overdue", never: "No recorded attempts", unknown: "Outcome unavailable" };
const MAINTENANCE_OUTCOMES = { success: "Succeeded", failure: "Failed", unknown: "Outcome unavailable" };

function settingsMaintenanceAdmin() {
  return typeof state.profile?.id === "string" && Boolean(state.profile.id) && state.profile.role === "admin" && isAdminProfile();
}

function settingsMaintenancePanel(token) {
  if (!settingsMaintenanceAdmin()) return null;
  const profile = state.profile, profileId = profile.id;
  const button = el("button", { type: "button", class: "btn btn-secondary", id: "settings-maintenance-refresh", text: "Refresh history",
    onclick: () => {
      if (button.isConnected && byId("settings-maintenance-refresh") === button && state.profile === profile && profile.id === profileId && token === routeToken)
        loadSettingsMaintenance(token);
    } });
  return el("section", { class: "panel settings-part", id: "settings-maintenance", "aria-labelledby": "settings-maintenance-title" },
    el("h2", { id: "settings-maintenance-title", text: "Database maintenance" }),
    el("p", { class: "sub", text: "Recorded backup, export, integrity check and restore check results. Refreshing only reads history." }),
    el("div", { class: "settings-fields", id: "settings-maintenance-content" }, loadingBox("Loading maintenance history.", { small: true })),
    el("div", { class: "actions" }, button));
}

/** The response and its health claims belong only to this connected Settings panel and selected admin. */
async function loadSettingsMaintenance(token) {
  const host = byId("settings-maintenance-content"), profile = state.profile;
  if (!host || !settingsMaintenanceAdmin() || token !== routeToken || parseHash().path !== "settings" || host.maintenanceBusy) return;
  const profileId = profile.id;
  const sequence = host.maintenanceRequest = (host.maintenanceRequest || 0) + 1;
  const button = byId("settings-maintenance-refresh");
  const hadFocus = document.activeElement === button;
  const here = () => host.isConnected && byId("settings-maintenance-content") === host && token === routeToken
    && sequence === host.maintenanceRequest && state.profile === profile && profile.id === profileId && settingsMaintenanceAdmin() && parseHash().path === "settings";
  host.maintenanceBusy = true;
  if (button) button.disabled = true;
  clear(host).append(loadingBox("Loading maintenance history.", { small: true }));
  try {
    const data = await api("/api/settings/maintenance");
    if (!here()) return;
    if (!settingsMaintenanceAnswer(data)) throw new Error("Unverified maintenance history");
    renderSettingsMaintenance(host, data);
  } catch (error) {
    if (!here()) return;
    // An unexpected API/connector error may contain private paths or database details.
    clear(host).append(el("p", { class: "form-error", role: "alert",
      text: "Maintenance history is unavailable. Refresh history to try again." }));
  } finally {
    if (here()) {
      host.maintenanceBusy = false;
      if (button && button.isConnected && byId("settings-maintenance-refresh") === button) {
        button.disabled = false;
        if (hadFocus && (!document.activeElement || document.activeElement === document.body || document.activeElement === button)) button.focus();
      }
    }
  }
}

function settingsMaintenanceDate(value) {
  const match = typeof value === "string" && /^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(?:\.\d{1,6})?(?:Z|\+00:00)$/.exec(value);
  if (!match) return false;
  const [year, month, day, hour, minute, second] = match.slice(1, 7).map(Number);
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return year > 0 && month >= 1 && month <= 12 && day >= 1 && day <= days[month - 1]
    && hour < 24 && minute < 60 && second < 60 && Number.isFinite(new Date(value).getTime());
}

/** Verify the small public projection before displaying any current-health wording. */
function settingsMaintenanceAnswer(data) {
  const checked = new Date(data?.checked_at).getTime();
  const run = row => row === null || Boolean(row && typeof row === "object"
    && Object.hasOwn(MAINTENANCE_OUTCOMES, row.outcome)
    && [row.started_at, row.finished_at].every(value => value === null || settingsMaintenanceDate(value))
    && (row.outcome === "unknown" || (settingsMaintenanceDate(row.started_at) && settingsMaintenanceDate(row.finished_at)
      && new Date(row.started_at) <= new Date(row.finished_at) && new Date(row.finished_at).getTime() <= checked)));
  return Boolean(data?.available === true && settingsMaintenanceDate(data.checked_at) && data.recent_limit === 5
    && Array.isArray(data.jobs) && data.jobs.length === MAINTENANCE_JOBS.length
    && data.jobs.every((job, index) => job && job.kind === MAINTENANCE_JOBS[index][0]
      && Object.hasOwn(MAINTENANCE_HEALTH, job.health) && ["current", "stale", "never", "unknown"].includes(job.freshness)
      && run(job.latest) && run(job.last_success) && (job.last_success === null || job.last_success.outcome === "success")
      && (job.health !== "success" || (job.latest?.outcome === "success" && job.last_success && job.freshness === "current"))
      && (job.health !== "stale" || (job.latest?.outcome === "success" && job.last_success && job.freshness === "stale"))
      && (job.health !== "failure" || job.latest?.outcome === "failure")
      && (job.latest?.outcome !== "unknown" || job.health === "unknown")
      && (job.health !== "never" || (job.latest === null && job.last_success === null && job.freshness === "never" && !job.recent?.length))
      && Array.isArray(job.recent) && job.recent.length <= data.recent_limit && job.recent.every(row => row !== null && run(row))
      && job.interval && job.interval.unit === (job.kind === "restore_check" ? "days" : "hours")
      && job.interval.source === (job.kind === "restore_check" ? "restore_check_days" : "stale_backup_hours")
      && job.interval.basis === (["dump", "export"].includes(job.kind) ? "finished_at" : "started_at")
      && (!["current", "stale"].includes(job.freshness) || (job.last_success && job.interval.value !== null))
      && (job.interval.value === null || (typeof job.interval.value === "number" && Number.isFinite(job.interval.value) && job.interval.value >= 0))));
}

function settingsMaintenanceWhen(value) {
  return settingsMaintenanceDate(value) ? new Date(value).toLocaleString("en-AU") : "Date unavailable";
}

function settingsMaintenanceRun(row) {
  return `${MAINTENANCE_OUTCOMES[row.outcome]}. Started: ${settingsMaintenanceWhen(row.started_at)}. Finished: ${settingsMaintenanceWhen(row.finished_at)}.`;
}

function renderSettingsMaintenance(host, data) {
  clear(host).append(el("p", { class: "sub", text: `History checked: ${settingsMaintenanceWhen(data.checked_at)}.` }));
  for (const [index, job] of data.jobs.entries()) {
    const interval = job.interval, period = interval.value === null ? null : `${interval.value} ${interval.unit}`;
    const policy = job.kind === "export" ? "Export uses the nightly grace period" : "Freshness interval";
    const freshness = { current: "Last success is within its freshness interval.", stale: "Last success is overdue.",
      never: "No successful run is recorded.", unknown: "Freshness is unknown." }[job.freshness];
    host.append(el("section", { "data-maintenance-job": job.kind },
      el("h3", { text: MAINTENANCE_JOBS[index][1] }),
      el("p", { text: `Latest status: ${MAINTENANCE_HEALTH[job.health]}.` }),
      el("p", { text: job.latest ? `Latest attempt: ${settingsMaintenanceRun(job.latest)}` : "Latest attempt: No recorded attempts." }),
      el("p", { text: job.last_success ? `Last successful run: ${settingsMaintenanceRun(job.last_success)}` : "Last successful run: None recorded." }),
      el("p", { class: "sub", text: `${freshness} ${period ? `${policy}: ${period}, from ${interval.basis === "started_at" ? "start" : "finish"}.` : "Freshness interval unavailable."}` }),
      job.recent.length ? el("details", {}, el("summary", { text: `Recent attempts (${job.recent.length})` }),
        el("ol", {}, job.recent.map(row => el("li", { text: settingsMaintenanceRun(row) })))) : null));
  }
}

/** Load the simulations setting into its part; a failure is said there, with Try again (loadSimulations
 * itself keeps quiet, since the footer's version check says when Deck Lab can't be reached). */
async function settingsSimulations(token) {
  await loadSimulations();
  const part = byId("sim-loading");
  if (token !== routeToken || !part || !state.profile || state.simulations) return;
  clear(part).append(loadFailed("The simulations setting", state.simulationsError, () => {
    clear(part).append(loadingBox("Loading the simulations setting…", { small: true }));
    settingsSimulations(token);
  }));
}

// ----------------------------------------------------------------- visits

const VISIT_DAYS = 30;
const VISIT_CHANNELS = { home: "at home", remote: "from outside the home" };

/** Fetch GET /api/visits and draw it into #visits-list, unless the page has moved on (token). */
async function loadVisits(token) {
  let data;
  try {
    data = await api(`/api/visits?days=${VISIT_DAYS}`);
  } catch (e) {
    const box = byId("visits-list");
    if (box && token === routeToken) clear(box).append(loadFailed("Visits", e, () => {
      clear(box).append(loadingBox("Loading visits…", { small: true }));
      loadVisits(token);
    }));
    return;
  }
  if (token === routeToken) renderVisits(data);
}

/** A page a visitor opened, in words: its route's name, and its deck's title on a deck's pages (a deck the
 * viewer can't see comes with no id and a title such as "one of Jordan's decks"). */
function visitPageName(page) {
  const label = routeFor(page.route).label;
  if (page.deck) return `${label}: ${page.title || page.deck}`;
  return page.title ? `${label}: ${page.title}` : label;
}

/** "Today 2:05 pm", "Yesterday 9:10 am" or the date in words, for an ISO time. */
function visitWhen(iso) {
  const when = new Date(iso);
  return Number.isNaN(when.getTime()) ? iso : `${activityDayName(when)} ${activityTime(when)}`;
}

/** /api/visits's answer as one block per profile: when last seen and from where, how many days in the window,
 * then the pages opened last and most often. A profile never seen says so. */
function renderVisits(data) {
  const box = byId("visits-list");
  if (!box) return;
  clear(box);
  const days = data.days || VISIT_DAYS;
  for (const person of data.people || []) {
    const facts = person.seen
      ? [`Last seen ${visitWhen(person.last_seen)} ${VISIT_CHANNELS[person.last_channel] || ""}`.trim(),
        `${person.days} of the last ${days} days`, `first seen ${person.first_seen}`]
      : ["Not seen yet"];
    const pages = (title, list, count) => (list.length ? el("p", { class: "visits-pages" },
      el("span", { class: "visits-label", text: `${title}: ` }),
      list.map((p) => (count ? `${visitPageName(p)} (${p.opens})` : visitPageName(p))).join(", ")) : null);
    box.append(el("div", { class: "visits-person", "data-profile": person.profile },
      el("h3", { text: person.name }),
      el("p", { class: "sub", text: facts.join(" · ") }),
      pages("Recently", person.recent || [], false),
      pages("Most opened", person.often || [], true)));
  }
  if (!box.children.length) box.append(emptyBox("No one has been added to Deck Lab yet."));
}
