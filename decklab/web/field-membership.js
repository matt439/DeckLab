/* Read-only current field membership. Kept outside field.js's game-result redraws: this list describes
 * today's selector, not the lists behind saved games. Loaded only when its native disclosure is opened. */
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
  return { format: answer.format, rows, counts: { included: counts.included, opponents: counts.opponents,
    manual_excluded: counts.manual_excluded } };
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
