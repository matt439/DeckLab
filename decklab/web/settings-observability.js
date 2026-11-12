/* A home admin sees only safe operational references: page kind, error type, receipt time and reference. Any admin
   sees Data sources (E11-S85): each download's last good fetch and last failure, fixed names and times only. */
"use strict";

function settingsErrorReferences() {
  if (!state.profile || state.profile.role !== "admin" || (state.profile.space || HOME_SPACE) !== HOME_SPACE) return null;
  const list = el("div", {}, el("p", {class: "sub", text: "Show the most recent reported references."}));
  const refresh = el("button", {type: "button", class: "btn btn-secondary", text: "Show references"});
  const panel = el("section", {class: "panel settings-part", id: "settings-errors"},
    el("h2", {text: "Page-error references"}),
    el("p", {class: "sub", text: "Reported errors only. References contain no person, deck, message or file details."}), refresh, list);
  const owner = {profile: state.profile, token: routeToken, hash: location.hash, main: $("#main")};
  const here = () => state.profile === owner.profile && routeToken === owner.token && location.hash === owner.hash
    && $("#main") === owner.main && panel.isConnected && owner.main.contains(panel);
  async function read() {
    if (!here() || refresh.disabled) return;
    refresh.disabled = true;
    clear(list).append(loadingBox("Loading page-error references…", {small: true}));
    try {
      const data = await api("/api/settings/errors");
      if (!here()) return;
      clear(list);
      if (!data.ready) { list.append(el("p", {class: "note note-crit", text: data.message || "Error references are unavailable."})); return; }
      if (!Array.isArray(data.events) || data.events.some(row => !row || !/^[0-9a-f]{32}$/.test(row.reference || "")
          || !PAGE_ERROR_KINDS.has(row.page) || typeof row.type !== "string" || row.type.length > 30
          || typeof row.at !== "string" || !Number.isFinite(new Date(row.at).getTime()))) {
        list.append(el("p", {class: "note note-crit", text: "The error-reference answer couldn't be read."})); return;
      }
      if (!data.events.length) { list.append(emptyBox("No page errors have been reported.")); return; }
      list.append(el("ul", {class: "plain-list"}, data.events.map(row => el("li", {},
        el("code", {text: row.reference}),
        el("p", {class: "sub", text: `${row.page} · ${row.type} · ${new Date(row.at).toLocaleString(LOCALE)}`})))));
    } catch (error) {
      if (here()) clear(list).append(loadFailed("Error references", error));
    } finally {
      if (here()) { refresh.disabled = false; refresh.textContent = "Refresh"; }
    }
  }
  refresh.addEventListener("click", read);
  return panel;
}

// ------------------------------------------------------- data sources (E11-S85)

const DATA_SOURCE_KEYS = ["scryfall", "fx", "rulings", "spellbook", "mtgjson", "edhrec", "gauntlet"];
const DATA_SOURCE_STATES = {ok: "Working", failing: "Last try failed", never: "No fetch recorded", stale: "Not refreshing"};

/** An admin's list of each downloaded source's last good fetch and last failure (GET /api/settings/data-sources).
 * Reading changes and fetches nothing; the answer holds fixed source names and times only. */
function settingsDataSources() {
  if (!state.profile || state.profile.role !== "admin") return null;
  const list = el("div", {}, el("p", {class: "sub", text: "Show each download's last good fetch and last failure."}));
  const refresh = el("button", {type: "button", class: "btn btn-secondary", id: "settings-data-sources-show", text: "Show data sources"});
  const panel = el("section", {class: "panel settings-part", id: "settings-data-sources", "aria-labelledby": "settings-data-sources-title"},
    el("h2", {id: "settings-data-sources-title", text: "Data sources"}),
    el("p", {class: "sub", text: "When Deck Lab last fetched each download it relies on, and when a fetch last failed. The server log on the PC says why."}),
    list, el("div", {class: "actions"}, refresh));
  const owner = {profile: state.profile, token: routeToken, hash: location.hash, main: $("#main")};
  const here = () => state.profile === owner.profile && routeToken === owner.token && location.hash === owner.hash
    && $("#main") === owner.main && panel.isConnected && owner.main.contains(panel);
  async function read() {
    if (!here() || refresh.disabled) return;
    refresh.disabled = true;
    clear(list).append(loadingBox("Loading data sources…", {small: true}));
    try {
      const data = await api("/api/settings/data-sources");
      if (!here()) return;
      clear(list);
      if (!dataSourcesAnswer(data)) { list.append(el("p", {class: "note note-crit", text: "The data-sources answer couldn't be read."})); return; }
      if (!data.readable) list.append(el("p", {class: "note note-crit", text: "The record of fetches on the PC can't be read, so no fetch is shown. The next fetch starts it afresh."}));
      if (data.card_data?.warning) list.append(el("p", {class: "note note-warn", text: data.card_data.warning}));
      list.append(el("ul", {class: "plain-list"}, data.sources.map(row => el("li", {"data-source": row.key},
        el("strong", {text: row.label}), " ", el("span", {class: "sub", text: `· ${DATA_SOURCE_STATES[row.state]}`}),
        el("p", {class: "sub", text: `Last good fetch: ${dataSourceTime(row.last_ok)} · Last failure: ${dataSourceTime(row.last_failure)}`})))));
    } catch (error) {
      if (here()) clear(list).append(loadFailed("Data sources", error));
    } finally {
      if (here()) { refresh.disabled = false; refresh.textContent = "Refresh"; }
    }
  }
  refresh.addEventListener("click", read);
  return panel;
}

function dataSourceTime(value) {
  return value === null ? "none recorded" : new Date(value).toLocaleString(LOCALE);
}

/** Check the small answer before showing any health words. */
function dataSourcesAnswer(data) {
  const time = value => value === null || (typeof value === "string" && value.length <= 40 && Number.isFinite(new Date(value).getTime()));
  return Boolean(data && typeof data.readable === "boolean" && Array.isArray(data.sources)
    && data.sources.length === DATA_SOURCE_KEYS.length
    && data.sources.every((row, index) => row && row.key === DATA_SOURCE_KEYS[index] && typeof row.label === "string"
      && row.label.length <= 60 && Object.hasOwn(DATA_SOURCE_STATES, row.state) && time(row.last_ok) && time(row.last_failure))
    && (data.card_data === null || (data.card_data && typeof data.card_data.stale === "boolean"
      && (data.card_data.warning === null || (typeof data.card_data.warning === "string" && data.card_data.warning.length <= 400)))));
}
