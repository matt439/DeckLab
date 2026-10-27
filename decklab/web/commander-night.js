/* The household's recorded Commander night: dated notes, not enforced rules.
 * Settings edits one audited record; deck pages receive only their permitted projection. */
"use strict";

function commanderNightAdmin() { return ownSpace() === HOME_SPACE && isAdminProfile(); }

/** Beside the deck's declared aim, without treating a matching number as a power assessment. */
function commanderNightPart(data) {
  if (data.summary.kind !== "commander" || deckSpaceOf(data.summary.id) !== HOME_SPACE || ownSpace() !== HOME_SPACE) return null;
  const saved = data.commander_night;
  if (!saved) return null;
  if (saved.unavailable) return el("div", { class: "commander-night" },
    note("The recorded Commander night couldn't be loaded. Check the venue's expectations before playing."));
  const night = saved.night;
  if (!night) return null;
  const target = data.summary.target_bracket, aim = night.target_bracket;
  const low = night.published_min, high = night.published_max;
  const range = low == null ? "No published bracket range recorded."
    : low === high ? `Published venue bracket: ${low}.` : `Published venue range: Brackets ${low}–${high}.`;
  let comparison = "";
  if (target && aim) comparison = target === aim ? `This deck's target matches the household's Bracket ${aim} aim.`
    : `This deck targets Bracket ${target}; the household aims for Bracket ${aim} at this night.`;
  else if (target && low != null) comparison = target >= low && target <= high
    ? `This deck's target Bracket ${target} is within the recorded venue range.`
    : `This deck's target Bracket ${target} is outside the recorded venue range.`;
  else if (!target) comparison = "This deck has no target bracket recorded.";
  return el("div", { class: "commander-night" },
    el("h3", { text: night.name }),
    night.venue ? el("p", { class: "sub", text: `Venue: ${night.venue}` }) : null,
    el("p", { text: aim ? `Household aim: Bracket ${aim}. ${range}` : `No household target recorded. ${range}` }),
    comparison ? el("p", { class: "commander-night-comparison", text: comparison }) : null,
    night.house_rules ? el("p", { class: "commander-night-rules", text: night.house_rules }) : null,
    el("p", { class: "sub", text: night.checked_on ? `Last checked: ${night.checked_on}.` : "Checked date unknown." }),
    el("p", { class: "sub", text: "These are notes for the pregame conversation. Deck Lab does not enforce house rules or establish that the deck meets the night's expectations." }));
}

function commanderNightSettings() {
  if (!commanderNightAdmin()) return null;
  return el("section", { class: "panel settings-part", id: "settings-commander-night", "aria-labelledby": "settings-night-title" },
    el("h2", { id: "settings-night-title", text: "Commander night" }),
    el("p", { class: "sub", text: "Record the household's usual night and what its table expects. Everyone at home sees these notes on home Commander deck pages. Only home admins change them." }),
    el("div", { id: "commander-night-settings" }, loadingBox("Loading the recorded Commander night…")));
}

/** A late load must not cross a route/profile switch or replace a newer request or edit form. */
async function loadCommanderNightSettings(token) {
  const host = byId("commander-night-settings"), profile = state.profile && state.profile.id;
  if (!host || !commanderNightAdmin()) return;
  const sequence = host.nightRequest = (host.nightRequest || 0) + 1;
  const here = () => host.isConnected && token === routeToken && sequence === host.nightRequest
    && profile === (state.profile && state.profile.id) && commanderNightAdmin();
  clear(host).append(loadingBox("Loading the recorded Commander night…"));
  try {
    const data = await api("/api/commander-night");
    if (here()) drawCommanderNightSettings(host, data, token, profile);
  } catch (error) {
    if (!here()) return;
    clear(host).append(el("p", { class: "form-error", role: "alert", text: `The Commander night couldn't be loaded: ${error.message}` }),
      el("button", { type: "button", class: "btn btn-secondary", text: "Try again", onclick: () => loadCommanderNightSettings(token) }));
  }
}

function nightBracketSelect(id, blank) {
  return el("select", { id }, el("option", { value: "", text: blank }),
    [1, 2, 3, 4, 5].map((n) => el("option", { value: String(n), text: `Bracket ${n}` })));
}

function drawCommanderNightSettings(host, data, token, profile) {
  if (!data.can_edit || !Number.isInteger(data.revision) || data.revision < 0) {
    clear(host).append(el("p", { class: "sub", text: "The recorded Commander night can't be edited here." }));
    return;
  }
  const night = data.night || {}, ctx = { host, token, profile, revision: data.revision, busy: false, stale: false };
  ctx.form = el("form", { class: "settings-fields commander-night-form", onsubmit: (event) => {
    event.preventDefault(); saveCommanderNight(ctx);
  } });
  ctx.here = () => ctx.form.isConnected && ctx.token === routeToken
    && ctx.profile === (state.profile && state.profile.id) && commanderNightAdmin();
  // HTML maxlength counts UTF-16 units; validation below counts Unicode characters as the server does.
  ctx.name = el("input", { id: "night-name", type: "text", maxlength: 240, required: true });
  ctx.venue = el("input", { id: "night-venue", type: "text", maxlength: 240 });
  ctx.target = nightBracketSelect("night-target", "No household target recorded");
  ctx.low = nightBracketSelect("night-published-min", "No published range recorded");
  ctx.high = nightBracketSelect("night-published-max", "No published range recorded");
  ctx.rules = el("textarea", { id: "night-rules", maxlength: 3000, rows: 4 });
  ctx.checked = el("input", { id: "night-checked", type: "date" });
  ctx.error = el("p", { class: "form-error", role: "alert" });
  ctx.status = el("p", { class: "sub", role: "status" });
  ctx.reload = el("button", { type: "button", class: "btn btn-secondary", text: "Load current saved note", hidden: true,
    onclick: () => { if (ctx.here() && !ctx.busy) loadCommanderNightSettings(token); } });
  ctx.save = el("button", { type: "submit", class: "btn btn-primary", text: "Save Commander night" });
  const field = (label, input, hint) => el("label", { class: "field", for: input.id }, el("span", { text: label }), input,
    hint ? el("span", { class: "field-hint", text: hint }) : null);
  add(ctx.form, [
    !data.night ? el("p", { class: "sub", text: "No Commander night is recorded. Blank targets and dates stay unknown." }) : null,
    field("Night name (required)", ctx.name, "Up to 120 characters."), field("Venue (optional)", ctx.venue, "Up to 120 characters."),
    field("Household target bracket", ctx.target, "The bracket you want to play at this night; separate from the venue's published range."),
    el("div", { class: "commander-night-range" }, field("Published range: from", ctx.low), field("Published range: to", ctx.high)),
    el("p", { class: "field-hint", text: "Leave both range fields blank if the venue hasn't published one. For one bracket, choose it in both fields." }),
    field("House rules and table notes", ctx.rules, "Up to 1,500 characters. They are shown as written and aren't enforced by Deck Lab."),
    field("Date last checked", ctx.checked, "Leave blank if unknown. Saving doesn't mark these notes as checked today."),
    ctx.error, ctx.status, ctx.reload, el("div", { class: "actions" }, ctx.save)]);
  const values = [[ctx.name, night.name], [ctx.venue, night.venue], [ctx.target, night.target_bracket],
    [ctx.low, night.published_min], [ctx.high, night.published_max], [ctx.rules, night.house_rules], [ctx.checked, night.checked_on]];
  values.forEach(([input, value]) => { input.value = value == null ? "" : String(value); });
  ctx.controls = values.map(([input]) => input);
  for (const input of ctx.controls) input.addEventListener("input", () => { ctx.status.textContent = ""; });
  clear(host).append(ctx.form);
  if (data.night) {
    ctx.reason = el("input", { id: "night-remove-reason", type: "text", maxlength: 1000 });
    ctx.confirm = el("input", { type: "checkbox" });
    ctx.remove = el("button", { type: "button", class: "btn btn-danger", text: "Remove recorded night",
      onclick: () => saveCommanderNight(ctx, true) });
    ctx.form.append(el("details", { class: "more" }, el("summary", { text: "Remove this recorded night" }),
      field("Reason for removal (required)", ctx.reason, "Up to 500 characters."),
      el("label", { class: "choice" }, ctx.confirm, el("span", { text: "I confirm removing the recorded night and its notes." })), ctx.remove));
    ctx.controls.push(ctx.reason, ctx.confirm);
  }
  return ctx;
}

function commanderNightInput(ctx) {
  const bracket = (input) => input.value === "" ? null : Number(input.value);
  const night = { name: ctx.name.value.trim(), venue: ctx.venue.value.trim(), target_bracket: bracket(ctx.target),
    published_min: bracket(ctx.low), published_max: bracket(ctx.high), house_rules: ctx.rules.value.trim(), checked_on: ctx.checked.value };
  if (!night.name || [...night.name].length > 120 || [...night.venue].length > 120) throw new Error("Enter a night name; the name and venue may each use at most 120 characters.");
  if ([night.target_bracket, night.published_min, night.published_max].some((n) => n !== null && (!Number.isInteger(n) || n < 1 || n > 5)))
    throw new Error("Choose bracket numbers from 1 to 5.");
  if ((night.published_min === null) !== (night.published_max === null) || night.published_min > night.published_max)
    throw new Error("Choose both ends of the published range in order, or leave both blank.");
  if ([...night.house_rules].length > 1500) throw new Error("Keep house rules and table notes within 1,500 characters.");
  if (night.checked_on && !/^\d{4}-\d{2}-\d{2}$/.test(night.checked_on)) throw new Error("Use a valid date for Date last checked, or leave it blank.");
  return night;
}

async function saveCommanderNight(ctx, remove = false) {
  if (!ctx.here() || ctx.busy || ctx.stale) return;
  let night, reason;
  try {
    if (remove) {
      reason = ctx.reason.value.trim();
      if (!ctx.confirm.checked || !reason || [...reason].length > 500) throw new Error("Enter a reason of at most 500 characters and confirm removing this recorded night first.");
      night = null;
    } else night = commanderNightInput(ctx);
  } catch (error) { ctx.error.textContent = error.message; return; }
  ctx.busy = true; ctx.error.textContent = ""; ctx.status.textContent = remove ? "Removing recorded night…" : "Saving Commander night…";
  ctx.controls.forEach((input) => { input.disabled = true; });
  ctx.save.disabled = true; if (ctx.remove) ctx.remove.disabled = true;
  try {
    const data = await apiWrite("/api/commander-night", { profile: ctx.profile, expect: ctx.revision, night,
      ...(remove ? { reason } : {}) }, "PUT");
    if (!ctx.here()) return;
    const next = drawCommanderNightSettings(ctx.host, data, ctx.token, ctx.profile);
    if (next) next.status.textContent = remove ? "Recorded Commander night removed." : "Commander night saved.";
  } catch (error) {
    if (!ctx.here()) return;
    ctx.stale = error.status === 409;
    ctx.error.textContent = ctx.stale ? "The saved Commander night changed while this form was open. Your edits are still here. Load the current saved note to discard these edits before saving again."
      : `The Commander night couldn't be saved: ${error.message}`;
    ctx.status.textContent = ""; ctx.reload.hidden = !ctx.stale;
  } finally {
    ctx.busy = false;
    if (ctx.here()) {
      ctx.controls.forEach((input) => { input.disabled = false; });
      ctx.save.disabled = ctx.stale; if (ctx.remove) ctx.remove.disabled = ctx.stale;
    }
  }
}
