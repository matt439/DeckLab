/* Deck Lab's page: Settings (#/settings, decklab/UI-REVIEW.md 2.2), an admin's page. Who may start Forge
simulations and how many Forge workers the PC uses (GET/PUT /api/simulations, lib/api/simulations.py), Visits
(GET /api/visits, lib/api/visits.py: who has used Deck Lab, when, and the pages they opened), and About Deck Lab:
the running server's version, Check for updates and the card data. These used to sit in every page's footer;
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
        el("div", { class: "actions" }, check)))]);
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
  loadVisits(token);
  showFooter();
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
