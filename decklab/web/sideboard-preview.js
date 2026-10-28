/* A saved sideboard plan's exact post-board list and proposed game counts. Read-only: no run or save. */
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
  host.append(button);
  button.addEventListener("click", () => {
    if (!spvOwner(ctx) || button.disabled || keyboardDialog() || keyboardMenuOpen()) return;
    if (ctx.sheet && !ctx.sheet.closed) return;
    if (!ctx.frame) { ctx.frame = host.parentNode; ctx.frameParent = ctx.frame.parentNode; }
    spvOpen(ctx);
  });
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
  ctx.body.append(full, games, el("p", { class: "sub", text: "No test was started and no verdict is available." }));
}
