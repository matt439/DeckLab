/* Deck Lab's page: Restart Deck Lab, on the Settings page's About part (settings.js), a home admin's. GET
/api/server/restart (lib/api/server_restart.py) says whether a restart may start and what it would stop; POST
asks the PC to restart, after a confirmation here. The page then waits for a server with another started_at
(GET /api/status's build) and reloads. A restart is refused while the checkout has uncommitted code, and it
never applies database migrations. The "Restart needed" warning box (version.js) links here for a home admin.

Loaded after settings.js and before app.js. Nothing here runs at load.
*/
"use strict";

const RESTART_POLL_MS = 3000;
const RESTART_GIVE_UP_MS = 180000;

/** A named home admin: the only one the server lets restart Deck Lab. */
function mayRestartServer(profile = state.profile) {
  return Boolean(profile && typeof profile.id === "string" && profile.id && profile.role === "admin"
    && (!profile.space || profile.space === "home"));
}

function settingsRestartPart() {
  if (!mayRestartServer()) return null;
  return el("div", { class: "settings-fields", id: "server-restart" },
    el("p", { class: "sub", id: "server-restart-words", role: "status" }),
    el("div", { class: "actions", id: "server-restart-actions" }));
}

async function loadServerRestart(token) {
  const host = byId("server-restart");
  if (!host || token !== routeToken) return;
  try {
    const view = await api("/api/server/restart");
    if (token === routeToken && host.isConnected && !host.restarting) drawServerRestart(host, view);
  } catch (e) {
    if (token === routeToken && host.isConnected && !host.restarting) host.hidden = true;
  }
}

function drawServerRestart(host, view, note = "") {
  const words = byId("server-restart-words"), actions = clear(byId("server-restart-actions"));
  host.hidden = false;
  if (!view.may_restart) {
    words.textContent = view.why_not || "Deck Lab can't be restarted from here right now.";
    return;
  }
  words.textContent = note || "Restarting stops Deck Lab for about half a minute, then starts it with the latest committed code. "
    + "It doesn't apply database migrations.";
  actions.append(el("button", { type: "button", class: "btn btn-secondary", text: "Restart Deck Lab…",
    onclick: () => confirmServerRestart(host, view) }));
}

function confirmServerRestart(host, view, busy = view.busy || []) {
  const words = byId("server-restart-words"), actions = clear(byId("server-restart-actions"));
  words.textContent = "Restart Deck Lab now? Anyone using it is cut off until it's back."
    + (busy.length ? ` It would stop ${busy.join("; ")}; games already finished are kept.` : "");
  actions.append(
    el("button", { type: "button", class: "btn", text: busy.length ? "Restart anyway" : "Restart now",
      onclick: () => startServerRestart(host, view, busy.length > 0) }),
    el("button", { type: "button", class: "btn btn-secondary", text: "Cancel",
      onclick: () => drawServerRestart(host, view) }));
}

async function startServerRestart(host, view, anyway) {
  const words = byId("server-restart-words"), actions = clear(byId("server-restart-actions"));
  words.textContent = "Asking the PC to restart Deck Lab…";
  let answer;
  try {
    answer = await apiWrite("/api/server/restart", { anyway });
  } catch (e) {
    if (!host.isConnected) return;
    if (!e.status || e.status >= 502) {
      // No answer, or the off page through the tunnel: the server may have stopped before its answer came back.
      host.restarting = true;
      words.textContent = "Deck Lab didn't answer; it may be restarting. This page reloads when it's back…";
      waitForRestart(state.status?.build?.started_at || null, Date.now(), false);
      return;
    }
    if (e.status === 409 && e.data && Array.isArray(e.data.busy) && e.data.busy.length) {
      confirmServerRestart(host, view, e.data.busy);
      return;
    }
    drawServerRestart(host, { ...view, may_restart: e.status !== 409 ? view.may_restart : false, why_not: e.message },
      `The restart didn't start: ${e.message}`);
    return;
  }
  host.restarting = true;
  words.textContent = "Deck Lab is restarting. This page reloads when it's back…";
  actions.append(el("span", { class: "spinner spinner-small", "aria-hidden": "true" }));
  waitForRestart(answer.started_at, Date.now(), false);
}

/** Poll /api/status until a server started at another time answers (or, when the old one's start wasn't known,
 * any server after one that didn't answer), then reload the page. Failed requests (the server is down; through
 * the tunnel, the off page) just mean it isn't back yet. */
async function waitForRestart(before, since, wentDown) {
  if (Date.now() - since > RESTART_GIVE_UP_MS) {
    const words = byId("server-restart-words");
    if (words) words.textContent = "Deck Lab hasn't come back after three minutes. On the PC, "
      + "python -m decklab.lib.homenet status says what's wrong (decklab/data/logs/restart.log says what the restart did).";
    const actions = byId("server-restart-actions");
    if (actions) clear(actions).append(el("button", { type: "button", class: "btn btn-secondary", text: "Reload page", onclick: reloadDeckLab }));
    return;
  }
  try {
    const s = await api("/api/status");
    const started = s.build && s.build.started_at;
    if (before ? started && started !== before : wentDown) {
      reloadDeckLab();
      return;
    }
  } catch (e) {
    wentDown = true;        // not back yet
  }
  setTimeout(() => waitForRestart(before, since, wentDown), RESTART_POLL_MS);
}
