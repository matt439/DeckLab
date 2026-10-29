/* A saved sideboard plan's exact post-board list and proposed game counts, read-only, and its Forge tests
 * (E4-S16): Start in the preview (POST /api/play/sideboard-test, the simulations setting's reason beside it) and
 * the plan's tests with their verdicts and older-list marks (GET /api/play/sideboard-tests). Nothing is saved. */
"use strict";

const SPV_SECTIONS = ["Commander", "Companion", "Deck", "Sideboard"];
const SPV_PAGE = 20;

function spvText(value, maximum) {
  return typeof value === "string" && value.length <= maximum * 2 &&
    Array.from(value).length <= maximum && value.trim().length > 0 && !/[\u0000-\u001f\u007f]/.test(value) &&
    !Array.from(value).some(char => char.codePointAt(0) >= 0xd800 && char.codePointAt(0) <= 0xdfff);
}
function spvSha(value) { return typeof value === "string" && /^[a-f0-9]{64}$/.test(value); }
function spvCount(value) { return Number.isInteger(value) && value >= 0 && value <= 1200000; }
function spvKey(row) { return JSON.stringify([row.name, row.set, row.number, row.finish]); }
function spvMap(rows) {
  const result = new Map();
  for (const row of rows || []) result.set(spvKey(row), (result.get(spvKey(row)) || 0) + row.qty);
  return result;
}
function spvSame(left, right) {
  return left.size === right.size && [...left].every(([key, count]) => right.get(key) === count);
}
function spvSections(raw) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw) ||
      Object.keys(raw).some(key => !SPV_SECTIONS.includes(key))) return null;
  const sections = {}; let count = 0;
  for (const section of SPV_SECTIONS) {
    const rows = Object.hasOwn(raw, section) ? raw[section] : [];
    if (!Array.isArray(rows) || (count += rows.length) > 500) return null;
    sections[section] = [];
    for (const row of rows) {
      if (!row || !spvText(row.name, 300) || !Number.isInteger(row.qty) || row.qty <= 0 || row.qty > 999 ||
          !["nonfoil", "foil", "etched"].includes(row.finish) ||
          ![row.set, row.number].every(value => value === null || value === "" || spvText(value, 80))) return null;
      sections[section].push({ name: row.name, qty: row.qty, set: row.set, number: row.number, finish: row.finish });
    }
  }
  return sections.Deck.length ? sections : null;
}
function spvMoves(raw) {
  if (!Array.isArray(raw) || raw.length > 100) return null;
  const rows = [], seen = new Set();
  for (const row of raw) {
    if (!row || !spvText(row.name, 300) || seen.has(row.name) || !Number.isInteger(row.qty) || row.qty <= 0 || row.qty > 99) return null;
    seen.add(row.name); rows.push({ name: row.name, qty: row.qty });
  }
  return rows;
}

/** Copy the public display contract only; a damaged answer never produces partial lists or totals. */
function spvAnswer(ctx, answer) {
  if (!answer || answer.version !== 1 || answer.error != null || answer.plan?.id !== ctx.id ||
      answer.plan?.sha256 !== ctx.sha256 || !Number.isInteger(answer.plan?.revision) ||
      answer.plan.revision <= 0 || answer.plan.revision > 999999999) return null;
  const lists = {};
  for (const key of ["base", "post_board", "opponent"]) {
    const source = answer[key], expected = key === "opponent" ? ctx.opponent : ctx.base;
    if (!source || source.id !== expected.id || source.version !== expected.version ||
        !spvText(source.title, 500) || !spvSha(source.sha256) ||
        key !== "post_board" && source.sha256 !== expected.sha256 ||
        key === "post_board" && source.derived !== true) return null;
    lists[key] = { id: source.id, version: source.version, title: source.title, sha256: source.sha256 };
    if (key !== "opponent") {
      const sections = spvSections(source.sections);
      if (!sections) return null;
      lists[key].sections = sections;
    }
  }
  const before = lists.base.sections, after = lists.post_board.sections;
  if (lists.base.title !== lists.post_board.title ||
      SPV_SECTIONS.reduce((n, key) => n + before[key].length + after[key].length, 0) > 1200 ||
      !spvSame(spvMap(SPV_SECTIONS.flatMap(key => before[key])), spvMap(SPV_SECTIONS.flatMap(key => after[key]))) ||
      ["Commander", "Companion"].some(key => !spvSame(spvMap(before[key]), spvMap(after[key])))) return null;
  const changes = { out: spvMoves(answer.changes?.out), in: spvMoves(answer.changes?.in) };
  if (!changes.out?.length || !changes.in?.length || changes.out.some(row => changes.in.some(other => other.name === row.name)) ||
      changes.out.reduce((n, row) => n + row.qty, 0) !== changes.in.reduce((n, row) => n + row.qty, 0)) return null;
  const names = rows => { const result = new Map(); for (const row of rows) result.set(row.name, (result.get(row.name) || 0) + row.qty); return result; };
  const moved = names([...changes.in, ...changes.out]);
  for (const key of ["Deck", "Sideboard"]) {
    const left = names(before[key]), right = names(after[key]), ins = names(changes.in), outs = names(changes.out);
    for (const name of new Set([...left.keys(), ...right.keys(), ...moved.keys()])) {
      const difference = (right.get(name) || 0) - (left.get(name) || 0);
      const intent = (ins.get(name) || 0) - (outs.get(name) || 0);
      if (difference !== (key === "Deck" ? intent : -intent)) return null;
    }
  }
  const sum = (sections, keys) => keys.reduce((n, key) => n + sections[key].reduce((m, row) => m + row.qty, 0), 0);
  const counts = { main_before: sum(before, ["Commander", "Deck"]), main_after: sum(after, ["Commander", "Deck"]),
    sideboard_before: sum(before, ["Sideboard"]), sideboard_after: sum(after, ["Sideboard"]) };
  if (Object.entries(counts).some(([key, value]) => !spvCount(answer.counts?.[key]) || answer.counts[key] !== value) ||
      counts.main_before !== counts.main_after || counts.sideboard_before !== counts.sideboard_after) return null;
  const games = answer.game_plan;
  if (!games || !["proposed", "unavailable"].includes(games.status) || games.cached_work !== "not_checked" ||
      games.remaining_games !== null || games.execution !== "not_performed" || !Array.isArray(games.modes)) return null;
  const gameReason = games.status === "unavailable" ? games.reason : null;
  if (games.status === "unavailable" && (games.modes.length || !["format_mismatch", "format_unknown"].includes(gameReason)) ||
      games.status === "proposed" && games.modes.length !== 2) return null;
  const expected = [["quick", [200], 200, 400], ["ahead", [400, 800, 1600, 3200], 3200, 6400]];
  for (let i = 0; i < games.modes.length; i++) {
    const [id, targets, maximum, total] = expected[i], mode = games.modes[i];
    if (!mode || mode.id !== id || !Array.isArray(mode.targets) || mode.targets.length !== targets.length ||
        mode.targets.some((n, j) => n !== targets[j]) || mode.base_games_max !== maximum ||
        mode.post_board_games_max !== maximum || mode.total_games_max !== total) return null;
  }
  return { revision: answer.plan.revision, ...lists, changes, counts, gameReason };
}

/** The original action remains the owner; even a same-id replacement profile or page invalidates it. */
function spvOwner(ctx) {
  return ctx.token === routeToken && ctx.hash === location.hash && ctx.profile === state.profile &&
    ctx.profileId === state.profile?.id && ctx.main === $("#main") && ctx.host.isConnected &&
    ctx.main.contains(ctx.host) && ctx.host.contains(ctx.button) && ctx.button.isConnected &&
    ctx.button.parentNode === ctx.host && (!ctx.frame || ctx.host.parentNode === ctx.frame &&
      ctx.frame.parentNode === ctx.frameParent && ctx.main.contains(ctx.frame)) &&
    ctx.entry.record === ctx.record && ctx.entry.sha256 === ctx.sha256 && ctx.record.id === ctx.id &&
    [[ctx.record.deck, ctx.base], [ctx.record.opponent, ctx.opponent]].every(([live, saved]) =>
      live && !live.hidden && !live.removed && live.id === saved.id && live.version === saved.version && live.sha256 === saved.sha256) &&
    (!ctx.deck || ctx.screen === deckScreen && ctx.data === deckScreen?.data && ctx.view === deckScreen?.view);
}
function spvSheetHere(ctx) {
  return spvOwner(ctx) && !ctx.sheet.closed && ctx.dialog === ctx.sheet.dialog &&
    ctx.body === ctx.sheet.body && ctx.foot === ctx.sheet.foot && ctx.dialog.isConnected &&
    ctx.dialog.parentNode === ctx.dialogParent && ctx.dialog.contains(ctx.body) && ctx.dialog.contains(ctx.foot) &&
    ctx.foot.contains(ctx.retry) && ctx.foot.contains(ctx.done) && ctx.retry.isConnected && ctx.done.isConnected;
}
function spvTop(ctx) {
  return Array.from(document.querySelectorAll("dialog")).filter(node => node.isConnected &&
    (node.open || node.getAttribute("open") !== null)).at(-1) === ctx.dialog;
}

function sideboardPreviewAction(entry) {
  const plan = entry?.record;
  if (!state.profile || !plan || !/^[a-f0-9]{32}$/.test(plan.id || "") || !spvSha(entry.sha256)) return null;
  if ([plan.deck, plan.opponent].some(list => list?.hidden || list?.removed)) return el("p", { class: "sub", text:
    "A post-board preview is unavailable for this saved pair." });
  if ([plan.deck, plan.opponent].some(list => !list ||
        !spvText(list.id, 200) || !["target", "owned"].includes(list.version) || !spvSha(list.sha256))) return null;
  const host = el("div", { class: "actions sideboard-preview-action" });
  const button = el("button", { type: "button", class: "btn", text: "Preview post-board list" });
  const ctx = { host, button, entry, record: plan, id: plan.id, sha256: entry.sha256, main: $("#main"), token: routeToken,
    profile: state.profile, profileId: state.profile.id, hash: location.hash, deck: location.hash.startsWith("#/deck?"),
    screen: deckScreen, data: deckScreen?.data, view: deckScreen?.view,
    base: { id: plan.deck.id, version: plan.deck.version, sha256: plan.deck.sha256 },
    opponent: { id: plan.opponent.id, version: plan.opponent.version, sha256: plan.opponent.sha256 } };
  const tests = el("button", { type: "button", class: "btn", text: "Tests of this plan" });
  host.append(button, tests);
  const opener = (control, open) => () => {
    if (!spvOwner(ctx) || control.disabled || !host.contains(control) || keyboardDialog() || keyboardMenuOpen()) return;
    if (ctx.sheet && !ctx.sheet.closed) return;
    if (!ctx.frame) { ctx.frame = host.parentNode; ctx.frameParent = ctx.frame.parentNode; }
    open(ctx);
  };
  button.addEventListener("click", opener(button, spvOpen));
  tests.addEventListener("click", opener(tests, spvTestsOpen));
  return host;
}

function spvOpen(owner) {
  const ctx = { ...owner };
  const sheet = owner.sheet = ctx.sheet = openSheet("Preview post-board list", { wide: true });
  ctx.dialog = sheet.dialog; ctx.body = sheet.body; ctx.foot = sheet.foot;
  ctx.dialogParent = sheet.dialog.parentNode; ctx.sequence = 0; ctx.pending = false;
  ctx.done = el("button", { type: "button", class: "btn", text: "Done", onclick: () => {
    if (spvSheetHere(ctx) && spvTop(ctx)) sheet.close();
  } });
  ctx.retry = el("button", { type: "button", class: "btn", text: "Refresh preview", onclick: () => {
    if (spvSheetHere(ctx) && spvTop(ctx) && !ctx.pending && !ctx.retry.disabled) spvFetch(ctx);
  } });
  sheet.foot.append(ctx.done, ctx.retry);
  spvFetch(ctx);
  if (spvSheetHere(ctx) && spvTop(ctx)) ctx.done.focus();
}

async function spvFetch(ctx) {
  if (!spvSheetHere(ctx) || ctx.pending) return;
  const sequence = ++ctx.sequence;
  ctx.pending = true; ctx.retry.disabled = true; ctx.render = null;
  clear(ctx.body).append(loadingBox("Loading the saved plan's post-board preview."));
  const current = () => sequence === ctx.sequence && spvSheetHere(ctx);
  try {
    const answer = await api(`/api/play/sideboard-preview?id=${encodeURIComponent(ctx.id)}&sha256=${ctx.sha256}`);
    if (!current()) return;
    const copied = spvAnswer(ctx, answer);
    if (!copied) throw new Error("Preview unavailable");
    spvDraw(ctx, copied);
    ctx.retry.textContent = "Refresh preview";
  } catch (_) {
    if (!current()) return;
    clear(ctx.body).append(el("p", { class: "box box-warn", role: "status", text:
      "This saved plan couldn't be previewed. Its record or lists may have changed, or may no longer be available. Review the plan, or try again." }));
    ctx.retry.textContent = "Try again";
  } finally {
    if (current()) { ctx.pending = false; ctx.retry.disabled = false; }
  }
}

function spvPrinting(row) {
  return (row.set ? row.set.toUpperCase() + (row.number ? ` ${row.number}` : "") : "Any printing") + `; ${row.finish}`;
}
function spvRows(ctx, title, rows, columns, render) {
  const box = el("section", { class: "sideboard-preview-section" }, el("h3", { text: title }));
  if (!rows.length) { box.append(el("p", { class: "sub", text: "None." })); return box; }
  const tbody = el("tbody"), count = el("p", { class: "sub", role: "status" });
  const more = el("button", { type: "button", class: "btn", text: "Show more rows" });
  const table = el("table", { class: "data" }, el("caption", { class: "sr-only", text: title }),
    el("thead", {}, el("tr", {}, columns.map(text => el("th", { scope: "col", text })))), tbody);
  let shown = 0;
  const append = () => {
    for (const row of rows.slice(shown, shown + SPV_PAGE)) tbody.append(el("tr", {},
      row.map((text, i) => el(i ? "td" : "th", i ? { text } : { scope: "row", text }))));
    shown = Math.min(rows.length, shown + SPV_PAGE);
    count.textContent = `Showing ${shown} of ${rows.length} rows.`;
    if (shown === rows.length) { more.setAttribute("aria-disabled", "true"); more.textContent = "All rows shown"; }
  };
  more.addEventListener("click", () => {
    if (spvSheetHere(ctx) && spvTop(ctx) && ctx.render === render && !ctx.pending &&
        box.contains(more) && box.contains(table) && ctx.body.contains(box) && more.isConnected && !more.disabled && shown < rows.length) append();
  });
  box.append(count, table); if (rows.length > SPV_PAGE) box.append(more);
  append(); return box;
}

function spvDraw(ctx, answer) {
  const render = ctx.render = {};
  clear(ctx.body).append(el("p", { text: `${answer.base.title} against ${answer.opponent.title}; saved plan revision ${answer.revision}.` }),
    el("p", { class: "sub", text: "Read-only preview. The original deck lists and sideboard plan are unchanged. The derived list is not a saved deck revision." }),
    el("p", { text: `Main list: ${answer.counts.main_before} before, ${answer.counts.main_after} after. ` +
      `Sideboard: ${answer.counts.sideboard_before} before, ${answer.counts.sideboard_after} after.` }),
    el("p", { text: `Out: ${playNames(answer.changes.out)}. In: ${playNames(answer.changes.in)}.` }));
  let differences = 0;
  for (const key of SPV_SECTIONS) {
    const before = spvMap(answer.base.sections[key]), after = spvMap(answer.post_board.sections[key]);
    const rows = [...new Set([...before.keys(), ...after.keys()])].filter(id => before.get(id) !== after.get(id)).map(id => {
      const [name, set, number, finish] = JSON.parse(id);
      return [name, spvPrinting({ set, number, finish }), String(before.get(id) || 0), String(after.get(id) || 0)];
    });
    if (rows.length) { differences += rows.length; ctx.body.append(spvRows(ctx, `${SECTION_CAPTIONS[key] || key}: changes`, rows,
      ["Card", "Listed printing", "Before", "After"], render)); }
  }
  if (!differences) ctx.body.append(el("p", { class: "sub", text: "The lists have the same cards, sections and listed printings." }));
  const full = el("details", { class: "more" }, el("summary", { text: "Complete post-board list" }));
  for (const key of SPV_SECTIONS) if (answer.post_board.sections[key].length) full.append(spvRows(ctx, SECTION_CAPTIONS[key] || key,
    answer.post_board.sections[key].map(row => [row.name, spvPrinting(row), String(row.qty)]), ["Card", "Listed printing", "Copies"], render));
  const games = answer.gameReason ? el("section", {}, el("h3", { text: "Paired-game guide unavailable" }),
    el("p", { class: "sub", text: answer.gameReason === "format_mismatch"
      ? "These decks use different simulation formats. No paired-game count is proposed."
      : "The simulation format couldn't be verified. No paired-game count is proposed." }))
    : el("section", {}, el("h3", { text: "Proposed paired-game guide" }),
    el("p", { text: "Quick check: up to 200 base games and 200 post-board games (400 total)." }),
    el("p", { text: "Play until ahead: paired targets of 400, 800, 1,600 and 3,200 games per list; up to 6,400 games total." }),
    el("p", { class: "sub", text: "These are fresh-game upper bounds. Saved games and simulation setup have not been checked, so remaining games are unknown." }));
  const note = el("p", { class: "sub", text: "No test was started and no verdict is available." });
  ctx.body.append(full, games, note);
  if (!answer.gameReason) ctx.body.append(spvStart(ctx, render, note));
}

// ------------------------------------------------------------- testing the plan in Forge (E4-S16)

const SPV_VERDICTS = ["better", "slightly_better", "little_difference", "not_settled", "slightly_worse", "worse", "stopped", "error"];

/** Start (or join) the plan's paired test from the preview: Forge plays the post-board main list on the base
 * list's games. While the simulations setting refuses this viewer, Start is disabled with its reason under it
 * (simulationsGate, as syncRunControls words it); the server checks every start anyway. */
function spvStart(ctx, render, note) {
  const result = el("div", { role: "status" }), gate = simulationsGate();
  const buttons = ["Start quick check", "Start play until ahead"].map(text =>
    el("button", { type: "button", class: "btn", text, disabled: !gate.may }));
  const row = el("div", { class: "actions sideboard-test-start" }, buttons);
  const box = el("section", { class: "sideboard-test" }, el("h3", { text: "Test this plan" }),
    el("p", { class: "sub", text: "Forge plays the post-board main list on the base list's games against the opponent " +
      "and says whether the swap is better, worse or makes little difference. Games are best of one, so the " +
      "sideboard itself isn't played." }), row, gate.may ? null : el("p", { class: "run-blocked", text: gate.why }), result);
  buttons.forEach((button, i) => button.addEventListener("click", async () => {
    if (!spvSheetHere(ctx) || !spvTop(ctx) || ctx.render !== render || ctx.pending || button.disabled ||
        !box.isConnected || !ctx.body.contains(box)) return;
    const mode = i ? "ahead" : "quick", sequence = ctx.sequence;
    ctx.pending = true; buttons.forEach(node => { node.disabled = true; });
    clear(result).append(loadingBox("Starting the test…", { small: true }));
    const here = () => sequence === ctx.sequence && ctx.render === render && spvSheetHere(ctx) && ctx.body.contains(box);
    try {
      const answer = await apiWrite("/api/play/sideboard-test", { id: ctx.id, sha256: ctx.sha256, mode });
      if (!here()) return;
      if (!answer || answer.version !== 1 || answer.plan?.id !== ctx.id || answer.plan?.sha256 !== ctx.sha256 ||
          !spvSha(answer.test) || answer.link !== `#/variant?test=${answer.test}`) throw new Error("Unexpected answer");
      const words = spvText(answer.words, 500) ? answer.words : null;
      clear(result).append(el("p", { text: words || (["queued", "running"].includes(answer.status)
        ? "The test is playing on the PC. Its verdict shows on the test's page and under Tests of this plan."
        : "The test was started.") }), el("p", {}, el("a", { href: answer.link, text: "Open the test" })));
      note.textContent = "A test of this plan was started. The deck lists and the saved plan are unchanged.";
    } catch (error) {
      if (!here()) return;
      const text = error instanceof ApiError && error.status === 403 && spvText(error.message, 500) ? error.message
        : "The test couldn't be started. The plan or its lists may have changed, or Forge may be busy. Try again.";
      clear(result).append(el("p", { class: "box box-warn", text }));
    } finally {
      if (here()) { ctx.pending = false; buttons.forEach(node => { node.disabled = !simulationsGate().may; }); }
    }
  }));
  return box;
}

function spvTestsAnswer(ctx, answer) {
  if (!answer || answer.version !== 1 || answer.plan?.id !== ctx.id || answer.plan?.sha256 !== ctx.sha256 ||
      typeof answer.current !== "boolean" || !Array.isArray(answer.tests) || answer.tests.length > 200) return null;
  const tests = [];
  for (const item of answer.tests) {
    if (!item || !spvSha(item.test) || item.link !== `#/variant?test=${item.test}` ||
        typeof item.older_list !== "boolean" || typeof item.running !== "boolean" ||
        item.verdict != null && !SPV_VERDICTS.includes(item.verdict) ||
        item.words != null && !spvText(item.words, 500) || !spvCount(item.games_per_opponent) ||
        [item.done, item.total].some(n => n != null && !spvCount(n))) return null;
    tests.push({ test: item.test, link: item.link, older: item.older_list, running: item.running,
      words: item.words || null, games: item.games_per_opponent, done: item.done, total: item.total });
  }
  return { current: answer.current, tests };
}

function spvTestsOpen(owner) {
  const ctx = { ...owner };
  const sheet = owner.sheet = ctx.sheet = openSheet("Tests of this plan", { wide: true });
  ctx.dialog = sheet.dialog; ctx.body = sheet.body; ctx.foot = sheet.foot;
  ctx.dialogParent = sheet.dialog.parentNode; ctx.sequence = 0; ctx.pending = false;
  ctx.done = el("button", { type: "button", class: "btn", text: "Done", onclick: () => {
    if (spvSheetHere(ctx) && spvTop(ctx)) sheet.close();
  } });
  ctx.retry = el("button", { type: "button", class: "btn", text: "Refresh", onclick: () => {
    if (spvSheetHere(ctx) && spvTop(ctx) && !ctx.pending && !ctx.retry.disabled) spvTestsFetch(ctx);
  } });
  sheet.foot.append(ctx.done, ctx.retry);
  spvTestsFetch(ctx);
  if (spvSheetHere(ctx) && spvTop(ctx)) ctx.done.focus();
}

async function spvTestsFetch(ctx) {
  if (!spvSheetHere(ctx) || ctx.pending) return;
  const sequence = ++ctx.sequence;
  ctx.pending = true; ctx.retry.disabled = true;
  clear(ctx.body).append(loadingBox("Loading this plan's tests."));
  const current = () => sequence === ctx.sequence && spvSheetHere(ctx);
  try {
    const answer = spvTestsAnswer(ctx, await api(`/api/play/sideboard-tests?id=${encodeURIComponent(ctx.id)}&sha256=${ctx.sha256}`));
    if (!current()) return;
    if (!answer) throw new Error("Tests unavailable");
    clear(ctx.body);
    if (!answer.current) ctx.body.append(el("p", { class: "box box-warn", text:
      "A list in this plan has changed since it was saved. Its tests are for an older list: revise the plan to test it again." }));
    if (!answer.tests.length) ctx.body.append(el("p", { class: "sub", text:
      "No test of this plan yet. Preview the post-board list to start one." }));
    else ctx.body.append(el("ul", { class: "sideboard-tests" }, answer.tests.map(item => el("li", {},
      el("p", { text: item.words || (item.running ? "Playing on the PC." : "No verdict yet.") }),
      el("p", { class: "sub", text: [item.older ? "For an older list" : null,
        item.running && item.total ? `${item.done || 0} of ${item.total} games played` : null,
        !item.running && item.games ? `${item.games.toLocaleString("en-AU")} games a deck` : null].filter(Boolean).join(" · ") }),
      el("a", { href: item.link, text: "Open the test" })))));
    ctx.retry.textContent = "Refresh";
  } catch (_) {
    if (!current()) return;
    clear(ctx.body).append(el("p", { class: "box box-warn", role: "status", text:
      "This plan's tests couldn't be loaded. Its record or lists may no longer be available. Try again." }));
    ctx.retry.textContent = "Try again";
  } finally {
    if (current()) { ctx.pending = false; ctx.retry.disabled = false; }
  }
}
