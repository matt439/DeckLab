/* Current field membership. Kept outside field.js's game-result redraws: this list describes
 * today's selector, not the lists behind saved games. Loaded only when its native disclosure is opened.
 * A home admin (the answer's can_edit) also gets Change the field (E3-S23): preview one home list's saved
 * choice (POST /api/field/policy/preview, which writes nothing), then save exactly that preview. */
"use strict";

const FM_MAX_ROWS = 1000;
const FM_PAGE_ROWS = 20;             // two groups: at most forty list rows on first paint
const FM_MAX_ID = 512;
const FM_MAX_REASON = 64;
const FM_REASONS = {
  default: "Included by the field rules.",
  configured_add: "Added to the field by hand.",
  configured_remove: "Left out of the field by hand.",
  not_selected: "Not selected for this field.",
  other_version: "The field rules choose this deck's other version.",
  unreadable: "This list couldn't be read.",
  beginner_half: "Beginner Box halves play only as a pairing.",
  pairing: "Pairings aren't included automatically.",
  product_not_selected: "Not selected by the field rules.",
  product_not_intact: "Not recorded as kept intact.",
  product_status: "Its product's status doesn't select this list.",
  product_status_missing: "Its product's status isn't recorded.",
};

/** One stable disclosure, status and Refresh control, independent of whether any field games exist. */
function fieldMembership(data) {
  const summary = el("summary", { text: "Who's in the field" });
  const statusLine = el("p", { class: "sub", role: "status" });
  const rows = el("div", { class: "fv-membership-rows" });
  const refresh = el("button", { type: "button", class: "btn", "data-field-membership-refresh": true,
    text: "Refresh membership" });
  const body = el("div", { class: "fv-membership-body" },
    el("p", { class: "sub", text: "Current membership only. Saved game results have their own lists." }),
    statusLine, rows, el("div", { class: "actions" }, refresh));
  const details = el("details", { class: "more fv-membership" }, summary, body);
  const ctx = { details, statusLine, rows, refresh, data, summary: data.summary, screen: deckScreen,
    view: deckScreen?.view, token: routeToken, profile: state.profile, profileId: state.profile?.id,
    id: data.summary.id, version: data.version, pending: false, loaded: false, sequence: 0, render: null };
  details.addEventListener("toggle", () => {
    if (details.open && !ctx.loaded && !ctx.pending && fmHere(ctx)) fmRefresh(ctx);
  });
  refresh.addEventListener("click", () => {
    if (details.open && refresh.isConnected && details.contains(refresh) && !refresh.disabled && fmHere(ctx)) fmRefresh(ctx);
  });
  return details;
}

/** An answer belongs to this exact page, list, route and profile, including a replaced same-id profile. */
function fmHere(ctx) {
  if (!ctx.details.isConnected || !ctx.details.contains(ctx.rows) || !ctx.details.contains(ctx.statusLine) ||
      !ctx.details.contains(ctx.refresh) || ctx.token !== routeToken || ctx.profile !== state.profile ||
      ctx.profileId !== state.profile?.id || ctx.screen !== deckScreen || ctx.view !== deckScreen?.view ||
      ctx.data !== deckScreen?.data || ctx.summary !== ctx.data.summary || ctx.id !== ctx.summary.id ||
      ctx.version !== ctx.data.version) return false;
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  return location.hash.startsWith("#/deck?") && addressDeckId(params.get("id")) === ctx.id &&
    (params.get("v") === "owned" ? "owned" : "target") === ctx.version;
}

/** Copy only the bounded display contract. Incomplete responses never show partial rows or totals. */
function fmAnswer(ctx, answer) {
  if (!answer || answer.complete !== true || answer.error != null || answer.deck?.id !== ctx.id ||
      answer.deck?.version !== ctx.version || !["Constructed", "Commander"].includes(answer.format) ||
      !Array.isArray(answer.rows) || answer.rows.length > FM_MAX_ROWS) return null;
  const counts = answer.counts, seen = new Set(), rows = [];
  if (!counts || ![counts.included, counts.opponents, counts.manual_excluded].every((n) =>
    Number.isInteger(n) && n >= 0 && n <= FM_MAX_ROWS)) return null;
  for (const row of answer.rows) {
    if (!row || !fmDeckId(row.id) ||
        !fmBoundedText(row.title, 200) ||
        !["target", "owned"].includes(row.version) || typeof row.in_field !== "boolean" ||
        typeof row.opponent !== "boolean" || typeof row.reason !== "string" ||
        row.reason.length > FM_MAX_REASON || !/^[a-z]/.test(row.reason) || /[^a-z0-9_]/.test(row.reason) ||
        row.opponent && (!row.in_field || row.id === ctx.id)) return null;
    const key = `${row.id}\n${row.version}`;
    if (seen.has(key)) return null;
    seen.add(key);
    rows.push({ id: row.id, title: row.title, version: row.version, in_field: row.in_field,
      opponent: row.opponent, reason: row.reason });
  }
  if (rows.filter((row) => row.in_field).length !== counts.included ||
      rows.filter((row) => row.opponent).length !== counts.opponents ||
      rows.filter((row) => row.reason === "configured_remove").length !== counts.manual_excluded) return null;
  return { format: answer.format, rows, can_edit: answer.can_edit === true,
    counts: { included: counts.included, opponents: counts.opponents, manual_excluded: counts.manual_excluded } };
}

/** Python's title bound counts Unicode characters; reject huge strings before allocating that copy. */
function fmBoundedText(value, maximum) {
  return typeof value === "string" && value.length <= maximum * 2 && Array.from(value).length <= maximum;
}

/** A display ceiling, not a new stored-data rule: legacy deck slugs need not fit today's generated slug. */
function fmDeckId(value) {
  if (!fmBoundedText(value, FM_MAX_ID) || /[\u0000-\u001f\u007f\\]/.test(value)) return false;
  const parts = value.split("/");
  if (parts.some((part) => !part || part === "." || part === "..")) return false;
  if (["casual", "commander"].includes(parts[0])) return parts.length === 2;
  if (parts[0] === "product") return parts.length === 2 || parts.length === 3;
  if (parts[0] === "pairing") return parts.length === 2 && parts[1].split("+").length === 2 &&
    parts[1].split("+").every(Boolean);
  return parts.length === 3 && parts[0].length <= 40 && /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(parts[0]) &&
    ["casual", "commander"].includes(parts[1]);
}

async function fmRefresh(ctx) {
  if (!fmHere(ctx) || ctx.pending) return;
  const sequence = ++ctx.sequence;
  ctx.pending = true;
  ctx.render = null;
  ctx.refresh.disabled = true;
  ctx.statusLine.textContent = "Loading current field membership.";
  clear(ctx.rows);
  const current = () => sequence === ctx.sequence && fmHere(ctx) && ctx.refresh.isConnected &&
    ctx.details.contains(ctx.refresh);
  try {
    const answer = await api(`/api/field/membership?id=${encodeURIComponent(ctx.id)}&version=${ctx.version}`);
    if (!current()) return;
    const copied = fmAnswer(ctx, answer);
    if (!copied) throw new Error("Membership unavailable");
    fvKeepPlace(() => fmDraw(ctx, copied));
  } catch (_) {
    if (!current()) return;
    ctx.statusLine.textContent = "Who's in the field couldn't be loaded. Try again.";
    ctx.refresh.textContent = "Try again";
    ctx.loaded = true;
  } finally {
    if (current()) { ctx.pending = false; ctx.refresh.disabled = false; }
  }
}

function fmDraw(ctx, answer) {
  const { counts } = answer;
  ctx.loaded = true;
  ctx.refresh.textContent = "Refresh membership";
  ctx.statusLine.textContent = `${answer.format}: ${plural(counts.included, "list")} included; ` +
    `${plural(counts.opponents, "opponent")} for this ${listName(ctx.version, true)}. ` +
    `${plural(counts.manual_excluded, "list")} left out by hand.`;
  const included = answer.rows.filter((row) => row.in_field);
  const excluded = answer.rows.filter((row) => !row.in_field);
  const render = ctx.render = {};
  clear(ctx.rows);
  for (const [title, group, empty] of [["Included", included, "No lists are included."],
    ["Left out", excluded, "No visible lists are left out."]]) {
    const panel = el("div", { class: "fv-membership-group" }, el("h3", { text: `${title} (${group.length})` }));
    ctx.rows.append(panel);
    if (!group.length) { panel.append(el("p", { class: "sub", text: empty })); continue; }
    const list = el("ul", { class: "fv-membership-list" });
    const count = el("p", { class: "sub", role: "status" });
    const more = el("button", { type: "button", class: "btn fv-membership-more",
      text: `Show more ${title.toLowerCase()} lists` });
    const part = { panel, list, count, more, title: title.toLowerCase(), rows: group, shown: 0 };
    panel.append(count, list);
    if (group.length > FM_PAGE_ROWS) panel.append(more);
    more.addEventListener("click", (event) => {
      if (event.defaultPrevented || !fmHere(ctx) || ctx.pending || ctx.render !== render ||
          !ctx.details.open || event.currentTarget !== more || !more.isConnected || !keyboardShown(more) ||
          more.disabled || !ctx.rows.contains(panel) || !panel.contains(more) || !panel.contains(list) ||
          part.shown >= part.rows.length || keyboardDialog() || keyboardMenuOpen()) return;
      fvKeepPlace(() => fmAppendRows(ctx, part));
    });
    fmAppendRows(ctx, part);
  }
  if (answer.can_edit) {
    const choices = fmChoices(ctx, answer);
    if (choices) ctx.rows.append(choices);
  }
}

/** Local expansion retains old links and the original button, including focus on the final batch. */
function fmAppendRows(ctx, part) {
  const next = part.rows.slice(part.shown, part.shown + FM_PAGE_ROWS);
  for (const row of next) part.list.append(fmRow(ctx, row));
  part.shown += next.length;
  part.count.textContent = `Showing ${part.shown} of ${part.rows.length} ${part.title} lists.`;
  const complete = part.shown === part.rows.length;
  part.more.setAttribute("aria-disabled", String(complete));
  if (complete) part.more.textContent = `All ${part.title} lists shown`;
}

function fmRow(ctx, row) {
  const self = row.id === ctx.id;
  const reason = Object.hasOwn(FM_REASONS, row.reason) ? FM_REASONS[row.reason]
    : "The field rules determined this membership.";
  return el("li", {},
    el("a", { href: deckHref(row.id, row.version), class: "fv-membership-link" },
      el("strong", { text: row.title }), el("span", { class: "sub", text: listName(row.version) })),
    el("p", { class: "sub", text: reason }),
    self ? el("p", { class: "sub", text: row.in_field
      ? "This deck is included, but never plays itself."
      : row.version === ctx.version ? "This is the list you're viewing." : "Another list of this deck." }) : null);
}

const FM_CHOICE_MODES = [["include", "Include this list"], ["exclude", "Leave the deck out"],
  ["rules", "Follow the field rules"]];
const FM_CHOICE_NOW = { legacy: "follows the field rules and any older hand edits", include: "is included by hand",
  exclude: "is left out by hand", rules: "follows the field rules" };
const FM_HOUSE = { Constructed: "casual", Commander: "commander" };
const FM_REVISION = /^(0|[1-9][0-9]{0,18})$/;

/** Change the field: a home house deck's list of this format, a choice, and a reason for leaving one out. */
function fmChoices(ctx, answer) {
  const lists = answer.rows.filter((row) => row.id.split("/").length === 2 && row.id.split("/")[0] === FM_HOUSE[answer.format]);
  if (!lists.length) return null;
  const choice = { ctx, render: ctx.render, format: answer.format, lists, preview: null, busy: false, saving: false, sequence: 0 };
  const field = (label, input) => el("label", { class: "field" }, el("span", { text: label }), input);
  choice.list = el("select", { "data-field-choice-list": true },
    lists.map((row, i) => el("option", { value: String(i), text: `${row.title}: ${listName(row.version)}` })));
  const own = lists.findIndex((row) => row.id === ctx.id && row.version === ctx.version);
  choice.list.value = String(Math.max(own, 0));
  choice.mode = el("select", { "data-field-choice-mode": true },
    FM_CHOICE_MODES.map(([value, text]) => el("option", { value, text })));
  choice.mode.value = "include";
  choice.reason = el("textarea", { "data-field-choice-reason": true, rows: 2, maxlength: 2000 });
  choice.status = el("p", { class: "sub", role: "status" });
  choice.check = el("button", { type: "button", class: "btn", "data-field-choice-preview": true, text: "Preview change" });
  choice.save = el("button", { type: "button", class: "btn btn-primary", "data-field-choice-save": true,
    text: "Save change", disabled: true });
  for (const input of [choice.list, choice.mode]) input.addEventListener("change", () => fmChoiceStale(choice));
  choice.check.addEventListener("click", () => fmChoicePreview(choice));
  choice.save.addEventListener("click", () => fmChoiceSave(choice));
  if (ctx.choiceNote) { choice.status.textContent = ctx.choiceNote; ctx.choiceNote = null; }
  return el("div", { class: "fv-membership-group fv-choices", "data-field-choices": true },
    el("h3", { text: "Change the field" }),
    el("p", { class: "sub", text: "A saved choice applies to the home field and stays with a deck when it's " +
      "renamed. Saving starts no games." }),
    field("List", choice.list), field("Choice", choice.mode),
    field("Why (needed to leave a deck out; kept in the change history only)", choice.reason),
    choice.status, el("div", { class: "actions" }, choice.check, choice.save));
}

/** The panel still belongs to the membership drawn for this page, list and profile, and no reload is pending. */
function fmChoiceHere(choice) {
  return fmHere(choice.ctx) && choice.ctx.render === choice.render && !choice.ctx.pending &&
    choice.ctx.rows.contains(choice.save);
}

function fmChoiceStale(choice) {
  if (choice.saving) return;
  choice.sequence++;
  choice.preview = null;
  choice.busy = false;
  choice.check.disabled = false;
  choice.save.disabled = true;
  choice.status.textContent = "";
}

/** Copy a preview only when it answers exactly the list and choice asked about. */
function fmChoiceAnswer(answer, row, mode, format) {
  if (!answer || answer.format !== format || answer.deck?.id !== row.id || answer.deck?.version !== row.version ||
      !Object.hasOwn(FM_CHOICE_NOW, answer.current?.mode) || answer.proposed?.mode !== mode ||
      typeof answer.changed !== "boolean" || typeof answer.ready !== "boolean" ||
      !(answer.message === null || fmBoundedText(answer.message, 300)) ||
      typeof answer.expect?.revision !== "string" || !FM_REVISION.test(answer.expect.revision) ||
      !answer.expect.proof || typeof answer.expect.proof !== "object" || Array.isArray(answer.expect.proof)) return null;
  return { format, row, mode, current: answer.current.mode, currentVersion: answer.current.version,
    changed: answer.changed, ready: answer.ready, message: answer.message,
    expect: { revision: answer.expect.revision, proof: answer.expect.proof } };
}

function fmChoiceNow(mode, version) {
  return FM_CHOICE_NOW[mode] + (mode === "include" && ["target", "owned"].includes(version) ? ` (${listName(version)})` : "");
}

/** The server's own words for a refusal (who may change it, a stale preview, the migrate command); never raw errors. */
function fmChoiceError(error, fallback) {
  return error instanceof ApiError && error.status >= 400 && fmBoundedText(error.message, 300) ? error.message : fallback;
}

async function fmChoicePreview(choice) {
  if (!fmChoiceHere(choice) || choice.busy) return;
  const row = choice.lists[Number(choice.list.value)], mode = choice.mode.value;
  if (!row || !FM_CHOICE_MODES.some(([value]) => value === mode)) return;
  const sequence = ++choice.sequence;
  const current = () => sequence === choice.sequence && fmChoiceHere(choice);
  Object.assign(choice, { busy: true, preview: null });
  choice.check.disabled = choice.save.disabled = true;
  choice.status.textContent = "Checking the change.";
  try {
    const answer = await apiWrite("/api/field/policy/preview", { id: row.id, version: row.version, mode });
    if (!current()) return;
    const preview = fmChoiceAnswer(answer, row, mode, choice.format);
    if (!preview) throw new Error("Preview unavailable");
    choice.preview = preview;
    choice.status.textContent = !preview.ready ? `${preview.message || "This choice can't be saved yet."} Nothing can be saved until then.`
      : !preview.changed ? `${row.title} ${fmChoiceNow(preview.current, preview.currentVersion)} already; nothing would change.`
      : `${row.title} ${fmChoiceNow(preview.current, preview.currentVersion)} now; after saving it ` +
        `${fmChoiceNow(mode, row.version)}.` + (mode === "exclude" ? " Say why before saving." : "");
    choice.save.disabled = !preview.ready || !preview.changed;
  } catch (error) {
    if (current()) choice.status.textContent = fmChoiceError(error, "The change couldn't be checked. Try again.");
  } finally {
    if (current()) { choice.busy = false; choice.check.disabled = false; }
  }
}

function fmChoiceLock(choice, locked) {
  for (const input of [choice.list, choice.mode, choice.reason, choice.check, choice.save]) input.disabled = locked;
}

/** Save exactly the shown preview; on success the membership is read again, which redraws this panel. */
async function fmChoiceSave(choice) {
  const preview = choice.preview, ctx = choice.ctx;
  if (!fmChoiceHere(choice) || choice.busy || !preview || !preview.ready || !preview.changed) return;
  const reason = choice.reason.value.trim();
  if (preview.mode === "exclude" && !reason) { choice.status.textContent = "Say why the deck is left out before saving."; return; }
  if ([...reason].length > 1000) { choice.status.textContent = "Keep the reason within 1,000 characters."; return; }
  const sequence = ++choice.sequence;
  const current = () => sequence === choice.sequence && fmChoiceHere(choice);
  // While saving, the list, choice and reason stay fixed so a change can't drop the save's answer.
  Object.assign(choice, { busy: true, saving: true });
  fmChoiceLock(choice, true);
  choice.status.textContent = "Saving the change.";
  try {
    await apiWrite("/api/field/policy", { format: preview.format, revision: preview.expect.revision,
      proof: preview.expect.proof, mode: preview.mode, ...(reason ? { reason } : {}) });
    choice.saving = false;
    if (!current()) return;
    ctx.choiceNote = `Saved: ${preview.row.title} ${fmChoiceNow(preview.mode, preview.row.version)}. ` +
      "The membership above was read again.";
    choice.busy = false;
    fmRefresh(ctx);
  } catch (error) {
    choice.saving = false;
    if (!current()) return;
    choice.preview = null;
    choice.busy = false;
    fmChoiceLock(choice, false);
    choice.save.disabled = true;
    choice.status.textContent = fmChoiceError(error, "The change couldn't be saved. Preview it again.");
  }
}
