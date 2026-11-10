/* A home admin sees only safe operational references: page kind, error type, receipt time and reference. */
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
