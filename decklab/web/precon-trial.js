/* Try a precon before buying it (E3-S39, lib/api/precon_trial.py): a published precon the space doesn't own,
 * saved as an ordinary idea deck of that space marked `- **Trial:** precon <FILE>`, so Forge can test it against
 * the space's own decks (Against the field, Play a matchup) and popular decks (the gauntlet). The trial is a
 * private deck of its space like any other: every privacy rule follows from that, and runs follow the
 * simulations setting (runGate), which this file only explains, never bypasses.
 *
 * openTrialSearch(space): the "Try a precon" sheet (Testing's "Try a precon…", #/matchups?open=precon): a search
 *   over GET /api/precons, then openTrialPrecon(file, space): GET /api/precons/trial says whether a trial already
 *   exists, whether this viewer may make one and whether the precon can be tested; "Try it in Forge" is
 *   POST /api/precons/trial, then the new deck's Testing tab (a 409 naming an existing trial opens that one).
 * ptrCoverageAction: the same create from "Precons we could build" (precon-coverage.js).
 * ptrDeckNotice: a trial deck's Overview notice (Remove trial: the existing retirement; Keep as a deck idea:
 *   POST /api/precons/trial/keep; Bought it? Add a precon).
 * ptrTrialsPart: after Add a precon, the trial decks of the same precon still in the library, to retire.
 * Late answers check the sheet, the route and the person who asked; writes go only through apiWrite. */
"use strict";

const PTR_SEARCH_MS = 250;

/** The space a trial goes in by default: the viewer's own, when they may add decks there, else the first
 * space they may add decks to; null when they may add decks nowhere. */
function ptrDefaultSpace() {
  const targets = createTargets();
  const own = ownSpace();
  if (targets.some((t) => t.space === own)) return own;
  return targets.length ? targets[0].space : null;
}

/** Where a trial deck opens: its Testing tab, at the popular decks. */
function ptrTrialHref(id) {
  return `${deckHref(id, "target")}&tab=matchups&part=gauntlet`;
}

/** "your decks" at home, else "<the space's name>'s decks", for the sheet's words. */
function ptrWhose(space) {
  return space === HOME_SPACE ? "your decks" : `${spaceName(space)}'s decks`;
}

/** The simulations setting's reason, when this viewer can't start runs now (names nobody: E10-S34). */
function ptrRunsNote() {
  const gate = runGate();
  if (gate.may) return null;
  return el("p", { class: "run-blocked ptr-runs", text: `${gate.why || "Simulations can't be started right now."} ` +
    "The trial deck can still be made; its tests wait until runs are allowed." });
}

function ptrHere(ctx, seq) {
  return (seq === undefined || seq === ctx.seq) && !ctx.sheet.closed && ctx.token === routeToken
    && ctx.profile === state.profile?.id;
}


// ------------------------------------------------------------------ the sheet

/** "Try a precon": search MTGJSON's published precons, pick one. */
function openTrialSearch(space = ptrDefaultSpace()) {
  if (!state.profile || !space) return null;
  const ctx = ptrSheet(space);
  ctx.input = el("input", { id: `ptr-q-${ctx.sheet.heading.id}`, type: "search", autocomplete: "off", placeholder: "Deck or set name" });
  ctx.input.addEventListener("input", () => {
    clearTimeout(ctx.timer);
    ctx.timer = setTimeout(() => ptrSearch(ctx), PTR_SEARCH_MS);
  });
  ctx.searchField = el("div", { class: "ptr-search" },
    el("p", { class: "sub", text: `Test a published precon you don't own in Forge, against ${ptrWhose(space)} and popular decks, ` +
      "before buying it. It's saved as a trial deck idea; nothing is added to the collection." }),
    el("label", { class: "field precon-search", for: ctx.input.id }, el("span", { class: "sr-only", text: "Find a precon" }), ctx.input));
  ctx.sheet.body.insertBefore(ctx.searchField, ctx.message);
  ctx.search = true;
  ptrSearchActions(ctx);
  ptrSearch(ctx);
  ctx.input.focus();
  return ctx;
}

function ptrSheet(space) {
  const sheet = colOpenSheet("Try a precon", { wide: true, onClose: () => clearTimeout(ctx.timer) });
  const ctx = { sheet, space, seq: 0, timer: null, busy: false, detail: null, search: false,
    token: routeToken, profile: state.profile?.id };
  ctx.message = el("div", { class: "col-sheet-message", role: "status", "aria-live": "polite" });
  ctx.area = el("div", { class: "ptr-area" });
  add(sheet.body, [ctx.message, ctx.area]);
  return ctx;
}

function ptrSearchActions(ctx) {
  sheetActions(ctx.sheet, [{ text: "Close", value: "close", onclick: () => ctx.sheet.close() }]);
}

async function ptrSearch(ctx) {
  if (!ptrHere(ctx) || ctx.detail) return;
  const seq = ++ctx.seq;
  const q = ctx.input.value.trim();
  clear(ctx.message).append(loadingBox("Finding precons…"));
  try {
    const answer = await api(`/api/precons?${new URLSearchParams({ q })}`);
    if (!ptrHere(ctx, seq) || ctx.detail) return;
    clear(ctx.message);
    const decks = answer.decks || [];
    add(clear(ctx.area), [
      decks.length ? el("ul", { class: "precon-list" }, decks.map((d) => el("li", {},
        el("button", { type: "button", class: "precon-pick", onclick: () => openTrialPrecon(d.file, ctx.space, ctx) },
          el("span", { class: "precon-pick-words" }, el("strong", { text: d.name }),
            el("small", { text: [d.set_name || String(d.code || "").toUpperCase(), d.type].filter(Boolean).join(" · ") })),
          d.released ? el("small", { class: "precon-pick-date", text: String(d.released).slice(0, 4) }) : null))))
        : emptyBox(q ? "No precon matches that. Only decks whose list has been published are here." : "No precons are listed.",
          null, { live: !!q }),
      answer.more ? el("p", { class: "result-count", text: "More match: type more of the name to narrow the list." }) : null,
      el("p", { class: "result-count", text: `Lists from MTGJSON${answer.date ? ` (updated ${answer.date})` : ""}, newest first.` })]);
  } catch (error) {
    if (!ptrHere(ctx, seq)) return;
    clear(ctx.message).append(loadFailed("The list of precons", error, () => ptrSearch(ctx)));
  }
}

function ptrBack(ctx) {
  ctx.detail = null;
  ctx.busy = false;
  ctx.searchField.hidden = false;
  ctx.sheet.heading.textContent = "Try a precon";
  ptrSearchActions(ctx);
  ptrSearch(ctx);
  ctx.input.focus();
}

/** One precon: whether it can be tried here, and "Try it in Forge" (or "Open its trial"). ctx: the search
 * sheet it was picked in, else a sheet of its own. */
async function openTrialPrecon(file, space = ptrDefaultSpace(), ctx = null) {
  if (!state.profile || !space) return null;
  ctx = ctx || ptrSheet(space);
  clearTimeout(ctx.timer);
  const seq = ++ctx.seq;
  const detail = { file };
  ctx.detail = detail;
  if (ctx.searchField) ctx.searchField.hidden = true;
  clear(ctx.area);
  clear(ctx.message).append(loadingBox("Reading the precon…"));
  const back = ctx.search ? { text: "← Back to the list", value: "back", onclick: () => ptrBack(ctx) } : null;
  sheetActions(ctx.sheet, [back, { text: "Close", value: "close", onclick: () => ctx.sheet.close() }]);
  try {
    const answer = await api(`/api/precons/trial?${new URLSearchParams({ file, space })}`);
    if (!ptrHere(ctx, seq) || ctx.detail !== detail) return ctx;
    detail.answer = answer;
    clear(ctx.message);
    ptrDrawPrecon(ctx, back);
  } catch (error) {
    if (!ptrHere(ctx, seq) || ctx.detail !== detail) return ctx;
    clear(ctx.message).append(loadFailed("The precon", error, () => openTrialPrecon(file, space, ctx)));
  }
  return ctx;
}

function ptrKindWords(a) {
  const cards = Number.isSafeInteger(a.cards) ? `${plural(a.cards, "card")}, ` : "";
  return a.kind === "commander" ? `${cards}played as a Commander deck` : `${cards}played as a 60-card deck`;
}

function ptrDrawPrecon(ctx, back) {
  const a = ctx.detail.answer;
  const d = a.deck || {};
  ctx.sheet.heading.textContent = d.name || "Try a precon";
  let primary = null;
  let action = null;
  if (a.trial) {
    action = el("p", {}, `You're already trying it: `, el("a", { href: ptrTrialHref(a.trial.id), text: a.trial.title }), ".");
    primary = { text: "Open its trial", kind: "primary", value: "open", onclick: () => { ctx.sheet.close(); location.hash = ptrTrialHref(a.trial.id); } };
  } else if (!a.testable) {
    action = el("p", { class: "box box-info", text: a.why_not_testable || "Forge can't test this precon against your decks." });
  } else if (!a.may_create) {
    action = el("p", { class: "box box-info", text: "You can't add decks here, so you can't try it." });
  } else {
    ctx.titleInput = el("input", { id: `ptr-title-${ctx.sheet.heading.id}`, type: "text", maxlength: "100", autocomplete: "off", value: a.title || "" });
    ctx.titleNote = el("p", { class: "field-problem ptr-title-note", role: "status" });
    action = el("div", { class: "ptr-make" },
      el("label", { class: "field ptr-title", for: ctx.titleInput.id }, el("span", { text: "Trial deck's title" }), ctx.titleInput),
      ctx.titleNote,
      el("p", { class: "sub", text: `Try it in Forge saves it as a trial deck idea in ${ptrWhose(ctx.space)}, with MTGJSON's list, ` +
        "and opens its Testing tab. Nothing is added to the collection. " +
        "Remove it on its deck page when you're done; Add a precon offers to once it's bought." }));
    primary = { text: "Try it in Forge", kind: "primary", value: "try", onclick: () => ptrTryTitled(ctx, d.file || ctx.detail.file) };
  }
  add(clear(ctx.area), [
    el("p", { class: "sub ptr-meta", text: [d.set_name || String(d.code || "").toUpperCase(), d.type, d.released ? `released ${d.released}` : null]
      .filter(Boolean).join(" · ") }),
    a.testable ? el("p", { class: "ptr-kind", text: ptrKindWords(a) }) : null,
    a.owned_deck ? el("p", { class: "box box-info" }, "You already have a deck from it: ",
      el("a", { href: deckHref(a.owned_deck.id, "target"), text: a.owned_deck.title }), ".") : null,
    action,
    a.testable && !a.trial ? ptrRunsNote() : null]);
  sheetActions(ctx.sheet, [back, primary, { text: "Close", value: "close", onclick: () => ctx.sheet.close() }]);
}


// ------------------------------------------------------------------ making a trial

/** POST /api/precons/trial, then the trial's Testing tab; a 409 naming a trial already made opens that one.
 * opts.alive() says whether the page that asked is still the one on screen. */
async function ptrCreate(body, { alive, failed, done, conflict = null }) {
  const requestHash = location.hash;
  try {
    const answer = await apiWrite("/api/precons/trial", body);
    state.library = null;
    if (!alive() || requestHash !== location.hash) return;
    done();
    toast(`${answer.title || "The trial deck"} is saved as a trial deck idea.`);
    location.hash = ptrTrialHref(answer.id);
  } catch (error) {
    if (!alive() || requestHash !== location.hash) return;
    const data = error.data || {};
    if (error.status === 409 && data.existing) {
      done();
      location.hash = ptrTrialHref(data.existing);
      return;
    }
    const problems = data.problems || (data.blocks || []).map((b) => ({ message: b.problem }));
    failed(el("div", { class: "box box-crit", role: "alert" }, el("p", { text: error.message }),
      problems.length ? el("ul", {}, problems.slice(0, 20).map((x) => el("li", { text: x.message || String(x) }))) : null));
    if (error.status === 409 && data.conflict && conflict) conflict();      // a taken title: pick another
  }
}

/** A title input's value, or null (its note saying why) when it's blank; "" when there's no input. */
function ptrTitle(input, note) {
  const title = input ? input.value.trim() : "";
  if (input && !title) {
    if (note) note.textContent = "The deck needs a title.";
    input.focus();
    return null;
  }
  if (note) note.textContent = "";
  return title;
}

function ptrFocusTitle(input) {
  if (!input || !input.isConnected) return;
  input.focus();
  if (typeof input.select === "function") input.select();
}

function ptrTryTitled(ctx, file) {
  if (ctx.busy || !ptrHere(ctx)) return;
  const title = ptrTitle(ctx.titleInput, ctx.titleNote);
  if (title === null) return;
  ptrTry(ctx, { file, space: ctx.space, title });
}

function ptrBusy(sheet, on) {
  for (const button of sheet.foot.querySelectorAll("button")) button.disabled = on;
}

async function ptrTry(ctx, body) {
  if (ctx.busy || !ptrHere(ctx)) return;
  const detail = ctx.detail;
  ctx.busy = true;
  ptrBusy(ctx.sheet, true);
  clear(ctx.message).append(loadingBox("Making the trial deck…"));
  await ptrCreate(body, {
    alive: () => ptrHere(ctx) && ctx.detail === detail,
    done: () => ctx.sheet.close(),
    failed: (box) => { ctx.busy = false; ptrBusy(ctx.sheet, false); clear(ctx.message).append(box); },
    conflict: () => ptrFocusTitle(ctx.titleInput) });
}

/** "Precons we could build"'s secondary "Try it in Forge" (precon-coverage.js drawCoveragePrecon), for a viewer
 * who may start decks there and a precon Forge can test; null otherwise. */
function ptrCoverageAction(ctx, p) {
  if (!p || !p.may_start || !p.testable) return null;
  return { text: "Try it in Forge", value: "trial", onclick: () => ptrCoverageTry(ctx) };
}

/** That view's note (precon-coverage.js drawCoveragePrecon): why the precon can't be tried, or the simulations
 * setting's reason when this viewer can't start runs (ptrRunsNote); null for neither. */
function ptrCoverageNotes(p) {
  if (!p || !p.may_start) return null;
  if (p.testable === false) return el("p", { class: "box box-info ptr-untestable", text: p.why_not_testable || "Forge can't test this precon." });
  return p.testable ? ptrRunsNote() : null;
}

async function ptrCoverageTry(ctx) {
  const detail = ctx.detail;
  if (ctx.busy || ctx.sheet.closed || !detail || !detail.answer || !colActive(ctx.cv)) return;
  const title = ptrTitle(ctx.titleInput, ctx.titleNote);         // the view's own title box names the trial too
  if (title === null) return;
  ctx.busy = true;
  ptrBusy(ctx.sheet, true);
  clear(ctx.message).append(loadingBox("Making the trial deck…"));
  await ptrCreate({ file: detail.answer.deck.file, space: ctx.cv.space, ...(title ? { title } : {}) }, {
    alive: () => !ctx.sheet.closed && colActive(ctx.cv) && ctx.detail === detail,
    done: () => ctx.sheet.close(),
    failed: (box) => { ctx.busy = false; ptrBusy(ctx.sheet, false); clear(ctx.message).append(box); },
    conflict: () => ptrFocusTitle(ctx.titleInput) });
}


// ------------------------------------------------------------------ the pages' hooks

/** Testing's "Try a precon…" beside Play a matchup (matchups-overview.js drawMatchups), for a viewer who may
 * add decks somewhere; #/matchups?open=precon opens the sheet once (the address loses ?open= first). */
function ptrTestingButton(main, params, token) {
  const space = ptrDefaultSpace();
  if (!space || !state.profile) return;
  const head = main.querySelector(".page-head");
  if (!head) return;
  let buttons = head.querySelector(".page-head-buttons");
  if (!buttons) head.append(buttons = el("div", { class: "actions page-head-buttons" }));
  buttons.append(el("button", { type: "button", class: "btn", text: "Try a precon…", onclick: () => openTrialSearch(space) }));
  if (params.get("open") !== "precon") return;
  setTimeout(() => {
    if (token !== routeToken) return;
    const query = new URLSearchParams(params);
    query.delete("open");
    history.replaceState(history.state, "", `#/matchups${query.toString() ? `?${query}` : ""}`);
    openTrialSearch(space);
  });
}

/** A trial deck's Overview notice (deck-overview.js deckOverviewPlayed: a trial isn't played at home). */
function ptrDeckNotice(data) {
  const s = data.summary;
  const editable = canEditDeck(s) && !s.read_only;
  const space = s.space || deckSpaceOf(s.id);
  const bought = colHash(space);
  const ctx = { ...ptrPageContext(), sending: false };
  const keep = editable ? el("button", { type: "button", class: "btn", text: "Keep as a deck idea",
    onclick: () => ptrKeep(data, keep, ctx) }) : null;
  return el("section", { class: "deck-section ptr-notice", "aria-labelledby": "h-overview-trial" },
    el("div", { class: "deck-section-head" }, el("h2", { id: "h-overview-trial", text: "A trial" })),
    el("p", {}, "You don't own this precon. Test it against your decks and popular decks on ",
      el("a", { href: ptrTrialHref(s.id), text: "Testing" }), "."),
    editable ? el("div", { class: "actions ptr-actions" },
      canRetireDeck(data) ? el("button", { type: "button", class: "btn", text: "Remove trial", onclick: () => openRetireDeck(data) }) : null,
      keep,
      el("a", { class: "btn btn-quiet", href: `${bought}${bought.includes("?") ? "&" : "?"}open=precon`, text: "Bought it? Add a precon" })) : null);
}

/** The page a late answer belongs to: the deck page's deck (its tabs rewrite the address in place, which is no
 * new page) or else the address; a real navigation moves routeToken on. */
function ptrPage() {
  const { path, params } = parseHash();
  return path === "deck" ? `deck:${params.get("id")}` : location.hash;
}

function ptrPageContext() {
  return { token: routeToken, profile: state.profile?.id, page: ptrPage() };
}

function ptrKeepHere(ctx) {
  return ctx.token === routeToken && ctx.profile === state.profile?.id && ctx.page === ptrPage();
}

async function ptrKeep(data, button, ctx) {
  const s = data.summary;
  if (ctx.sending || !ptrKeepHere(ctx)) return;
  // The text this page was drawn with (api/considering.py's sha256): a save since is the server's 409.
  const sha = data.considering && data.considering.sha256;
  if (!/^[0-9a-f]{64}$/.test(sha || "")) { toast("Reload the deck and try again."); return; }
  const choice = await ask(`Keep ${s.title} as a deck idea?`,
    ["It stops being a trial: it stays in the library as an idea, joins your decks' Forge field and counts when you shop " +
      "for missing cards. Its list and its test results stay as they are."],
    [{ value: "keep", text: "Keep as a deck idea", kind: "primary" }, { value: "cancel", text: "Cancel" }]);
  if (choice !== "keep" || ctx.sending || !ptrKeepHere(ctx)) return;
  ctx.sending = true;
  busy(button, "Keeping…");
  try {
    await apiWrite("/api/precons/trial/keep", { id: s.id, expected_sha: sha });
    state.library = null;
    if (!ptrKeepHere(ctx)) return;
    toast(`${s.title} is kept as a deck idea.`);
    route();
  } catch (error) {
    state.library = null;
    if (!ptrKeepHere(ctx)) return;
    toast(error.status === 409 ? `${error.message} Reload the deck and try again.` : error.message || String(error));
  } finally {
    ctx.sending = false;
    if (button.isConnected) unbusy(button);
  }
}

/** After Add a precon (editor-deckpage.js savedBox, from collection.js's answer.trials): the trial decks of the
 * same precon still in the library, each with "Remove the trial deck <title>" (the existing retirement). */
function ptrTrialsPart(trials) {
  if (!Array.isArray(trials) || !trials.length) return null;
  return el("div", { class: "ptr-bought" },
    el("p", { text: trials.length === 1 ? "You were trying this precon out: its trial deck is still in the library."
      : "You were trying this precon out: its trial decks are still in the library." }),
    el("div", { class: "actions ptr-actions" }, trials.map((t) => el("button", { type: "button", class: "btn",
      text: `Remove the trial deck ${t.title}`, onclick: (event) => ptrRetireTrial(t, event.currentTarget) }))));
}

async function ptrRetireTrial(trial, button) {
  const ctx = ptrPageContext();
  busy(button, "Checking…");
  try {
    const library = await api("/api/decks");
    if (!ptrKeepHere(ctx)) return;
    const summary = (library.decks || []).find((d) => d.id === trial.id);
    if (!summary) { toast(`${trial.title} is no longer in the library.`); return; }
    // The new deck's page stays (deck-retirement.js onRetired): a toast, then the page drawn again.
    const onRetired = (meta) => {
      if (!ptrKeepHere(ctx)) return;
      const saved = state.saved && state.saved.answer && state.saved.answer.precon;
      if (saved && Array.isArray(saved.trials)) saved.trials = saved.trials.filter((t) => t.id !== trial.id);
      toast(`${(meta && meta.title) || trial.title} has left the library. Its history and matchup results are kept.`);
      route();
    };
    if (!openRetireDeck({ summary }, { onRetired })) toast(`${trial.title} can't be retired here.`);
  } catch (error) {
    if (ptrKeepHere(ctx)) toast(error.message || String(error));
  } finally {
    if (button.isConnected) unbusy(button);
  }
}

/** The library's "Trial" pill (library.js deckStatusPill), in place of Idea. */
function ptrTrialPill() {
  return el("span", { class: "deck-status deck-status-idea ptr-trial", text: "Trial" });
}

/** A trial's title in Play a matchup's picker (matchups-overview.js deckPicker). */
function ptrPickerTitle(d) {
  return `${d.title} (trial, not owned)`;
}

/** The Popular decks board's "Not owned" chip for a trial deck's row (gauntlet-board.js gbRow). */
function ptrNotOwnedChip() {
  return status("info", "Not owned");
}
