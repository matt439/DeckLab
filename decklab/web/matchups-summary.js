/* Read-only context for the Matchups home's selected list. Pair rows may describe other versions or engines;
   field summaries name the current list; recorded swaps keep their original tested cards. Cached per viewer, list, revision and
   saved-result signature so running-progress redraws do not repeatedly fit a field. Loaded after the overview;
   field.js and variant.js supply the result renderers before any page is drawn. */
"use strict";

const MU_SELECTED_CACHE_KEEP = 12;
const MU_SELECTED_TIMEOUT_MS = 12000;
const MU_SELECTED_SWAP_TTL_MS = 45000; // ordinary matchup results do not capture every new or completed swap

function muSelectedContext(view, library, data, deck) {
  const summary = library.decks.find((d) => d.id === deck.id);
  const version = summary?.status === "built" && summary.built_version === "owned" && summary.versions?.includes("owned")
    ? "owned" : "target";
  const profile = state.profile?.id;
  const key = JSON.stringify([profile, deck.id, version, view.format, summary?.revision, library.decks_revision,
    (data.results || []).filter((r) => r.format === view.format)]);
  return { key, id: deck.id, title: summary?.title || deck.title, version, format: view.format, profile,
    token: routeToken, swaps: !!summary && !summary.read_only && /^(?:[^/]+\/)?(?:casual|commander)\//.test(deck.id) };
}

function muSelectedSummaryHere(view) {
  const c = view.selectedSummary;
  return !!c && !view.selectedPaused && c.host.isConnected && view.mode === "matchups" && view.deck === c.id
    && view.format === c.format && view.token === c.token && routeToken === c.token
    && view.profile === c.profile && state.profile?.id === c.profile && document.visibilityState !== "hidden";
}

/** Called by the existing foreground watcher's pause/stop hook and before changing selected context. */
function muCancelSelectedSummary(view) {
  view.selectedPaused = true;
  clearTimeout(view.selectedTimer); view.selectedTimer = null;
  const entry = view.selectedCache?.get(view.selectedSummary?.key);
  for (const panel of Object.values(entry?.panels || {})) {
    panel.sequence += 1;
    panel.cancel?.(); panel.cancel = null; panel.loading = false;
  }
}

/** A new DOM host may reuse the exact context's finished or in-flight reads after a progress redraw. */
function muSelectedSummary(view, library, data, deck) {
  view.token ??= routeToken; view.profile ??= state.profile?.id;
  const c = muSelectedContext(view, library, data, deck);
  if (view.selectedSummary?.key !== c.key) muCancelSelectedSummary(view);
  view.selectedPaused = false;
  view.selectedCache ||= new Map();
  if (!view.selectedCache.has(c.key)) {
    const panel = () => ({ answer: null, error: null, loading: false, sequence: 0, cancel: null });
    view.selectedCache.set(c.key, { panels: { field: panel(), swap: panel() } });
    while (view.selectedCache.size > MU_SELECTED_CACHE_KEEP) {
      const oldest = view.selectedCache.keys().next().value;
      view.selectedCache.delete(oldest);
    }
  }
  const link = (part) => `${deckHref(c.id, c.version)}&tab=matchups&part=${part}`;
  const section = (title, part, label) => {
    const body = el("div", { class: "mu-selected-content" });
    const node = el("section", { class: "mu-selected-panel", "aria-label": `${title}: ${c.title}, ${listName(c.version)}` },
      el("div", { class: "mu-selected-head" }, el("h3", { text: title }), el("a", { class: "btn", href: link(part), text: label })),
      el("p", { class: "sub mu-selected-list", text: `${c.title} · ${listName(c.version)}` }), body);
    return { node, body };
  };
  const field = section("Forge field", "field", "Field view");
  const swap = c.swaps ? section("Latest swap test", "tests", "All tests") : null;
  c.fieldHost = field.body; c.swapHost = swap?.body;
  c.host = el("div", { class: "mu-selected-summary" }, field.node, swap?.node);
  view.selectedSummary = c;
  muDrawSelectedSummary(view);
  clearTimeout(view.selectedTimer);
  // drawHome builds this just before attaching it. Defer the first reads until the host is attached.
  view.selectedTimer = setTimeout(() => { view.selectedTimer = null; muRefreshSelectedSummary(view); }, 0);
  return c.host;
}

function muSelectedFailure(host, view, kind, error) {
  const key = view.selectedSummary.key;
  add(host, [el("p", { class: "sub", role: "status", text: error }),
    el("button", { type: "button", class: "btn", text: "Try again", onclick: () => {
      if (!muSelectedSummaryHere(view) || view.selectedSummary.key !== key) return;
      const panel = view.selectedCache.get(key).panels[kind];
      panel.error = null; panel.answer = null;
      muReadSelectedPanel(view, kind);
    } })]);
}

function muDrawSelectedSummary(view) {
  const c = view.selectedSummary, entry = view.selectedCache.get(c.key);
  for (const kind of ["field", ...(c.swaps ? ["swap"] : [])]) {
    const host = kind === "field" ? c.fieldHost : c.swapHost, panel = entry.panels[kind];
    const signature = JSON.stringify([panel.loading, panel.error, panel.answer]);
    if (host.selectedSignature === signature) continue;
    host.selectedSignature = signature;
    replaceMatchupContent(host, () => muDrawSelectedPanel(host, view, kind, panel));
  }
}

function muDrawSelectedPanel(host, view, kind, panel) {
  clear(host); host.setAttribute("aria-busy", String(panel.loading));
  if (panel.error) { muSelectedFailure(host, view, kind, panel.error); return; }
  if (!panel.answer) { host.append(loadingBox(kind === "field" ? "Loading the Forge field..." : "Loading the latest test...")); return; }
  const a = panel.answer;
  if (kind === "swap") {
    add(host, [a.tests[0] ? el("p", { class: "sub", text: "Recorded tests keep the cards they tested. Open the test for its exact cards." }) : null,
      a.tests[0] ? el("ul", { class: "vt-test-list" }, vtTestItem(a.tests[0]))
        : el("p", { class: "sub", text: "No tests of this list yet." })]);
  } else if (!(a.opponents || []).length) {
    host.append(el("p", { class: "empty", text: "No other decks in this field yet." }));
  } else {
    add(host, [fvHeadline(a, { panel: false }), fvChips(a),
      Number.isFinite(a.rating?.h_points) ? el("p", { class: "sub" }, simNumbers(
        `Going first is worth about ${Math.round(a.rating.h_points)} points of win rate in these games.`)) : null]);
  }
}

/** Field answers echo the list. Variants' existing contract has only {tests}; its exact GET and sequence bind
 * it to this context. Check any supplied identity too, without requiring a backend contract expansion. */
function muCheckSelectedAnswer(kind, answer, c) {
  if (!answer || (kind === "field" && (!answer.deck || answer.format !== c.format)) ||
      (answer.deck && (answer.deck.id !== c.id || answer.deck.version !== c.version))) {
    throw new Error("The answer describes a different list. Try again.");
  }
  if (kind === "field" && (!Array.isArray(answer.opponents) ||
      !answer.opponents.every((o) => o && typeof o === "object" && !Array.isArray(o)))) {
    throw new Error("The field opponents couldn't be read. Try again.");
  }
  if (kind === "swap" && !Array.isArray(answer.tests)) throw new Error("The saved tests couldn't be read. Try again.");
  return answer;
}

async function muReadSelectedPanel(view, kind, refresh = false) {
  if (!muSelectedSummaryHere(view)) return;
  const c = view.selectedSummary, entry = view.selectedCache.get(c.key), panel = entry.panels[kind];
  if (panel.loading || (panel.answer && !refresh) || panel.error || (kind === "swap" && !c.swaps)) return;
  const sequence = ++panel.sequence, controller = new AbortController();
  const valid = () => panel.sequence === sequence && muSelectedSummaryHere(view) && view.selectedSummary.key === c.key;
  let deadline;
  const cancelled = new Promise((resolve, reject) => {
    panel.cancel = () => { controller.abort(); reject(new Error("Cancelled")); };
  });
  const timeout = new Promise((resolve, reject) => {
    deadline = setTimeout(() => { controller.abort(); reject(new Error("The PC took too long to answer. Try again.")); }, MU_SELECTED_TIMEOUT_MS);
  });
  panel.loading = true; muDrawSelectedSummary(view);
  const url = `/api/${kind === "field" ? "field" : "variants"}?id=${encodeURIComponent(c.id)}&version=${c.version}`;
  try {
    const answer = await Promise.race([api(url, { signal: controller.signal }), timeout, cancelled]);
    if (!valid() || controller.signal.aborted) return;
    panel.answer = muCheckSelectedAnswer(kind, answer, c); panel.answeredAt = Date.now();
  } catch (error) {
    if (valid()) panel.error = `${kind === "field" ? "The Forge field" : "The latest test"} couldn't be loaded. ${error.message}`;
  } finally {
    clearTimeout(deadline);
    if (panel.sequence === sequence) { panel.loading = false; panel.cancel = null; }
    if (valid()) muDrawSelectedSummary(view);
  }
}

/** Reuse expensive field fits until evidence changes. Saved swaps can change independently, so refresh them
 * through the existing foreground checks, at most once per idle interval. Failures offer an explicit retry. */
function muRefreshSelectedSummary(view) {
  view.selectedPaused = false;
  if (!muSelectedSummaryHere(view)) return Promise.resolve();
  const panel = view.selectedCache.get(view.selectedSummary.key).panels.swap;
  const refreshSwap = !!panel.answer && Date.now() - panel.answeredAt >= MU_SELECTED_SWAP_TTL_MS;
  return Promise.all([muReadSelectedPanel(view, "field"), muReadSelectedPanel(view, "swap", refreshSwap)]);
}
