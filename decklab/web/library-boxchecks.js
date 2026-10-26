/* Historical check-date filters use only the authorized summaries already loaded by the Library. */
"use strict";

function libBoxDate(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value) || Number(value.slice(0, 4)) < 1) return null;
  const date = new Date(value + "T00:00:00Z");
  return Number.isNaN(date.getTime()) || date.toISOString().slice(0, 10) !== value ? null : value;
}

function libBoxMode(value) { return ["unrecorded", "before"].includes(value) ? value : ""; }

function libBoxFilterParams(params) {
  const mode = libBoxMode(params.get("box_check"));
  return { box_check: mode, checked_before: mode === "before" ? libBoxDate(params.get("checked_before")) || "" : "" };
}

function libBoxFilterHash(params, filters) {
  const mode = libBoxMode(filters.box_check);
  if (mode) params.set("box_check", mode);
  if (mode === "before" && libBoxDate(filters.checked_before)) params.set("checked_before", filters.checked_before);
}

function libBoxChecksAllowed() { return Boolean(state.profile) && ownSpace() === HOME_SPACE && seesHomeInventory(state.may); }

function libBoxDeckScope(deck) {
  return deck && !deck.error && deck.status === "built" && ["casual", "commander"].includes(deck.kind)
    && typeof deck.id === "string" && /^(casual|commander)\/[^/]+$/.test(deck.id)
    && (deck.space || deckSpaceOf(deck.id)) === HOME_SPACE;
}

/** An omitted or malformed object is unknown/outside scope, never an unrecorded date. */
function libBoxCheckRecord(deck) {
  const record = deck?.box_check;
  return libBoxChecksAllowed() && libBoxDeckScope(deck) && record && typeof record === "object" && !Array.isArray(record)
    && Object.hasOwn(record, "checked_on") && (record.checked_on === null || libBoxDate(record.checked_on)) ? record : null;
}

function libMatchesBoxCheck(deck, filters) {
  const mode = libBoxMode(filters.box_check);
  if (!mode) return true;
  const record = libBoxCheckRecord(deck);
  if (!record) return false;
  return mode === "unrecorded" ? record.checked_on === null
    : Boolean(libBoxDate(filters.checked_before) && record.checked_on !== null && record.checked_on < filters.checked_before);
}

function libBoxCheckIssue(data, filters) {
  const mode = libBoxMode(filters.box_check);
  if (!mode) return { blocking: false, text: "" };
  if (!libBoxChecksAllowed()) return { blocking: true, text: "Check dates aren't available in this Library. Clear this filter to see decks." };
  if (mode === "before" && !libBoxDate(filters.checked_before)) return {
    blocking: true, text: "Choose a date to show decks checked strictly before it. No cutoff date has been chosen." };
  const scoped = (data.decks || []).filter(libBoxDeckScope), reliable = scoped.filter(libBoxCheckRecord);
  if (!reliable.length) return { blocking: true, text: scoped.length
    ? "Check dates aren't available for these decks. Reload the Library or clear this filter."
    : "Box check filters apply to built home decks. None are available here." };
  return { blocking: false, text: "Box check filters apply to built home decks."
    + (reliable.length < scoped.length ? " Decks without check-date information are excluded." : "") };
}

function libBoxCheckChoices() {
  return libBoxChecksAllowed() ? [["box_check", "Box check date", [["", "Any check date"],
    ["unrecorded", "No check date recorded"], ["before", "Checked before…"]]]] : [];
}

/** One retained native date input per surface; no age or today's date is inferred. */
function libBoxCutoff(id, filters, set, shown = false, current = () => true) {
  if (!libBoxChecksAllowed()) return { node: null, sync: () => {} };
  let accepted = libBoxDate(filters.checked_before) || "";
  const input = el("input", { id, type: "date", value: accepted, "aria-describedby": id + "-hint" });
  const node = el("label", { class: shown ? "field" : "field lib-select", for: id },
    el("span", { text: "Checked before date" }), input,
    el("span", { class: "field-hint", id: id + "-hint", text: "Only earlier dates match; a check on this date is excluded." }));
  const changed = () => {
    if (!current() || !input.isConnected || !node.contains(input) || libBoxMode(filters.box_check) !== "before") { input.value = accepted; return; }
    if (input.value === accepted) return;
    accepted = input.value; set("checked_before", accepted);
  };
  input.addEventListener("input", changed); input.addEventListener("change", changed);
  return { node, sync: () => {
    node.hidden = libBoxMode(filters.box_check) !== "before";
    input.disabled = node.hidden;
    accepted = libBoxDate(filters.checked_before) || "";
    if (input.value !== accepted) input.value = accepted;
  } };
}

function libBoxSelectedNote(deck) {
  const record = libBoxCheckRecord(deck);
  if (!record) return null;
  return el("p", { class: "sub lib-box-check-date" }, record.checked_on === null ? "No box check date is recorded. "
    : ["Last box check recorded: ", el("time", { datetime: record.checked_on, text: record.checked_on }), ". "],
  "Contents may have changed since.");
}
