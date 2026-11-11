/* Quiet, read-only save signals. Background checks never reload a page or write a draft. */
"use strict";

const CHANGE_POLL_MS = 10000;
const changeSignals = {profile: null, generation: 0, sequence: 0, latestSequence: 0, latest: null, page: null,
  available: true, request: null, at: null};

function changeRequestOwner() {
  if (changeSignals.profile !== state.profile) {
    stopChangeSignals(true);
    changeSignals.profile = state.profile;
  }
  return {profile: state.profile, token: routeToken, hash: location.hash, main: $("#main"),
    generation: changeSignals.generation, sequence: ++changeSignals.sequence};
}

function changeOwnerHere(owner) {
  return !!(owner && owner.profile === state.profile && owner.token === routeToken && owner.hash === location.hash
    && owner.main === $("#main") && owner.main?.isConnected);
}

function changeAnswer(value) {
  return value && value.ready === true && ["inventory", "decks", "library"].every(key =>
    typeof value[key] === "string" && /^[0-9a-f]{64}$/.test(value[key]));
}

function changeSame(a, b) {
  return !!(a && b && ["inventory", "decks", "library"].every(key => a[key] === b[key]));
}

function changesFromHeader(response, owner, method, poll = false) {
  let answer, committed;
  try {
    const raw = response.headers?.get?.("X-Deck-Lab-Changes");
    if (!raw || raw.length > 512) return;
    answer = JSON.parse(raw);
    committed = response.headers.get("X-Deck-Lab-Changes-Write") === "1";
  } catch (_) { return; }
  noteRevisions(answer, {owner, kind: !["GET", "HEAD"].includes(method) && committed ? "write" : poll ? "poll" : "read"});
  return !changeAnswer(answer) ? "unknown" : changeSame(answer, changeSignals.latest) ? "current" : "older";
}

function changesNoteRevisions(answer, {owner = changeRequestOwner(), kind = "poll"} = {}) {
  if (!owner.profile || owner.profile !== state.profile || owner.generation !== changeSignals.generation) return;
  if (!changeAnswer(answer)) {
    if (changeSignals.available) invalidateLibrary();
    changeSignals.available = false;         // retain the last good baseline; unknown is never an empty revision
    return;
  }
  if (kind === "write") {
    // A committed local write acknowledges its exact returned snapshot. Older in-flight
    // polls/reads cannot subsequently claim that this save came from another device.
    if (changeOwnerHere(owner)) {
      stopChangeSignals();
      changeSignals.generation++;
    }
    changeSignals.latestSequence = ++changeSignals.sequence;
  } else if (owner.sequence < changeSignals.latestSequence) {
    if (kind !== "read" || !changeOwnerHere(owner) || changeSignals.page && changeOwnerHere(changeSignals.page.owner)) return;
  } else changeSignals.latestSequence = owner.sequence;
  if (!changeSame(changeSignals.latest, answer) && changeSignals.latest) invalidateLibrary();
  changeSignals.available = true;
  if (kind === "write" || owner.sequence >= changeSignals.latestSequence || !changeSignals.latest) changeSignals.latest = answer;
  if (kind === "read" && changeOwnerHere(owner)) {
    if (!changeSignals.page || !changeOwnerHere(changeSignals.page.owner)) {
      if (changeSignals.page?.node) changeSignals.page.node.remove();
      changeSignals.page = {owner, base: answer, read: answer, changed: false, node: null};
    } else changeSignals.page.read = answer;
  } else if (kind === "write" && changeOwnerHere(owner) && changeSignals.page && changeOwnerHere(changeSignals.page.owner)) {
    changeSignals.page.base = answer;
    changeSignals.page.read = answer;
    changeSignals.page.changed = false;
  }
  renderRevisionNotice();
}

function changeRelevant(page) {
  const hash = String(location.hash || "").replace(/^#\/?/, ""), path = hash.split("?", 1)[0];
  if (!["deck", "edit", "new", "collection"].includes(path)) return false;
  const params = new URLSearchParams(hash.split("?")[1] || ""), own = state.profile?.space || HOME_SPACE;
  if (path === "collection" && (params.get("space") || own) !== own) return false;
  if (path === "deck" || path === "edit") {
    const first = (params.get("id") || "").split("/", 1)[0];
    const space = HOME_KINDS.includes(first) ? HOME_SPACE : first;
    if (space !== own) return page.base.library !== changeSignals.latest.library;
  }
  return page.base.inventory !== changeSignals.latest.inventory || page.base.decks !== changeSignals.latest.decks;
}

function renderRevisionNotice() {
  const page = changeSignals.page;
  if (!page || !changeOwnerHere(page.owner) || !changeSignals.latest) return;
  page.changed ||= changeRelevant(page);
  if (!page.changed) { if (page.node) page.node.remove(); page.node = null; return; }
  if (page.node?.isConnected) return;
  const button = el("button", {type: "button", class: "btn btn-quiet btn-inline", text: "Reload"});
  const node = el("div", {class: "note note-info change-notice", role: "status"},
    el("span", {text: "Saved on another device. Your open changes are kept."}), " ", button);
  page.node = node;
  button.addEventListener("click", () => reloadChangedPage(page, button));
  page.owner.main.insertBefore(node, page.owner.main.children[0] || null);
}

function acknowledgeChangeRead(page) {
  if (!changeOwnerHere(page.owner) || changeSignals.page !== page || !changeAnswer(page.read)) return;
  page.base = page.read;
  changeSignals.latest = page.read;
  changeSignals.latestSequence = ++changeSignals.sequence;
  page.changed = false;
  renderRevisionNotice();
}

async function reloadChangedPage(page, button) {
  const current = () => changeSignals.page === page && changeOwnerHere(page.owner);
  if (!current() || !button.isConnected || button.disabled) return;
  if ([...document.querySelectorAll("dialog")].some(dialog => dialog.open)) {
    toast("Your open edit is kept. Finish or keep that edit before reloading this page.");
    return;
  }
  button.disabled = true;
  try {
    const path = String(location.hash).replace(/^#\/?/, "").split("?", 1)[0];
    if ((path === "edit" || path === "new") && typeof editor !== "undefined" && editor && !editor.readOnly) {
      const ed = editor;
      if (ed.mode === "new") {
        const library = await api("/api/decks");
        if (!current() || editor !== ed) return;
        cacheLibrary(library);
        acknowledgeChangeRead(page);
        toast("Your unsaved deck is kept. Use Check to review it against the latest saved cards.");
      } else {
        const restored = await reapplyLatest(null, null, button, () => current() && button.isConnected && editor === ed);
        if (restored && current() && editor === ed) acknowledgeChangeRead(page);
      }
      return;
    }
    if (current()) route();
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    if (current()) toast(`The latest saved data couldn't be loaded: ${error.message}`);
  } finally {
    if (current() && button.isConnected) button.disabled = false;
  }
}

function pollChangeSignals(force = false) {
  if (!state.profile || document.visibilityState === "hidden" || changeSignals.request) return;
  if (!force && changeSignals.at !== null && Date.now() - changeSignals.at < CHANGE_POLL_MS) return;
  const owner = changeRequestOwner(), controller = new AbortController();
  changeSignals.request = controller;
  api("/api/changes", {poll: true, wakeHop: false, signal: controller.signal}).then(answer => {
    if (changeSignals.request === controller) noteRevisions(answer, {owner, kind: "poll"});
  }).catch(() => {
    if (changeSignals.request === controller) noteRevisions({ready: false}, {owner, kind: "poll"});
  }).finally(() => {
    if (changeSignals.request === controller) { changeSignals.request = null; changeSignals.at = Date.now(); }
  });
}

function stopChangeSignals(reset = false) {
  if (changeSignals.request) changeSignals.request.abort();
  changeSignals.request = null;
  if (!reset) return;
  if (changeSignals.page?.node) changeSignals.page.node.remove();
  changeSignals.page = null;
  changeSignals.latest = null;
  changeSignals.at = null;
  changeSignals.available = true;
  changeSignals.generation++;
}
