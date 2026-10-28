/* Storage locations (E8-S22) and the storage box's count (E8-S19): where a collection row's storage
 * copies are ("Row 2, B", "Binder"), set on the Collection page's card sheet and shown in the Card list
 * and Build decks' pull and put-back steps. Locations are kept apart from the rows (their sha256 stays
 * the eight columns'): the rows answers' "locations" {ready, rows: {colKey: text}} and "storage_box". */
"use strict";

const STORAGE_LOCATION_MAX = 40;
const STORAGE_LOCATION_ROWS = ["Row 1", "Row 2", "Row 3", "Row 4"];
const STORAGE_LOCATIONS_OFF = "Storage locations aren't available yet: Deck Lab's database needs updating on the PC.";

/** A locations answer as the page keeps it; null without one (an older server). */
function colLocations(answer) {
  if (!answer || typeof answer !== "object") return null;
  return { ready: answer.ready === true, rows: answer.rows && typeof answer.rows === "object" ? { ...answer.rows } : {} };
}

/** Take a rows answer's locations and storage box count into the page's view. */
function colTakeLocations(cv, answer) {
  if (!answer) return;
  if (answer.locations) cv.locations = colLocations(answer.locations);
  if (Object.hasOwn(answer, "storage_box")) cv.storageBoxCount = answer.storage_box || null;
}

/** A row's storage location, or "" when none is recorded (or not known on this view yet). */
function colLocationOf(cv, row) {
  const text = cv.locations && cv.locations.rows[colKey(row)];
  return typeof text === "string" ? text : "";
}

/** The storage words of a row with its location after them: "In storage · Row 2, B". */
function colWithLocation(cv, row, words) {
  const place = colLocationOf(cv, row);
  return place ? `${words} · ${place}` : words;
}

/** The suggestions the location box offers: the four rows of the storage box, then those already used. */
function colLocationChoices(cv) {
  const used = Object.values(cv.locations?.rows || {}).filter((text) => typeof text === "string" && text);
  return [...new Set([...STORAGE_LOCATION_ROWS, ...used.sort((a, b) => a.localeCompare(b))])];
}

/** The card sheet's Storage location field: a short line with suggestions. Off (with why) while the
 * database can't hold locations; on a view that hasn't loaded them yet it fills in once they arrive. */
function colLocationField(ctx, row, id) {
  const cv = ctx.cv;
  const list = el("datalist", { id: id("places") }, colLocationChoices(cv).map((text) => el("option", { value: text })));
  const input = el("input", { id: id("location"), type: "text", maxlength: STORAGE_LOCATION_MAX, autocomplete: "off",
    list: list.id, value: row ? colLocationOf(cv, row) : "", placeholder: "Such as Row 2, B or Binder" });
  const hint = el("small", { class: "field-hint", text: "Where its unsleeved copies are kept. Build decks shows it." });
  ctx.location = { input, list, hint, start: input.value, dirty: false };
  input.addEventListener("input", () => { ctx.location.dirty = true; });
  const off = () => {
    input.disabled = true;
    hint.textContent = STORAGE_LOCATIONS_OFF;
  };
  if (cv.locations && !cv.locations.ready) off();
  else if (!cv.locations) {
    // The Find cards view hasn't read the rows' locations yet: read them, then fill in the field.
    input.disabled = true;
    colEnsureRows(cv).then(() => {
      if (ctx.sheet.closed || !input.isConnected) return;
      if (!cv.locations || !cv.locations.ready) { off(); return; }
      input.disabled = false;
      if (!ctx.location.dirty && row) input.value = ctx.location.start = colLocationOf(cv, row);
      clear(list).append(...colLocationChoices(cv).map((text) => el("option", { value: text })));
    }).catch(() => { if (!ctx.sheet.closed) off(); });
  }
  return el("label", { class: "field col-field-location", for: input.id },
    el("span", { text: "Storage location" }), input, list, hint);
}

/** The location a save sends: only when it was changed (so an unchanged one is never written), else undefined. */
function colLocationToSend(ctx) {
  const place = ctx.location;
  if (!place || place.input.disabled) return undefined;
  const text = String(place.input.value || "").replace(/\s+/g, " ").trim();
  return text === String(place.start || "").replace(/\s+/g, " ").trim() ? undefined : text;
}

/** The storage box's fill on the Card list (home only): how many unsleeved cards it holds against its
 * capacity, said plainly when it's over. Nothing when it can't be worked out. */
function drawColStorageBox(cv) {
  if (!cv.boxNote) return;
  const box = cv.storageBoxCount;
  cv.boxNote.hidden = !box;
  if (!box) return;
  const counted = box.not_counted ? ` Basic lands (${plural(box.not_counted, "card")}) aren't counted.` : "";
  cv.boxNote.className = box.over ? "box box-warn col-storage-box" : "sub col-storage-box";
  cv.boxNote.textContent = box.over
    ? `The storage box is over capacity: about ${num(box.cards)} cards for about ${num(box.capacity)} places.${counted}`
    : `Storage box: about ${num(box.cards)} of ${num(box.capacity)} cards (the copies not in built decks or products kept intact).${counted}`;
}

/** Build decks: where a card to pull or put back is kept, as a tile's meta line, or null. */
function packLocationMeta(view, name) {
  const places = view.data?.storage_locations?.cards?.[name];
  return Array.isArray(places) && places.length ? places.join(" · ") : null;
}

/** Build decks: a note when locations can't be shown yet (the database needs updating). */
function packLocationNote(view) {
  const found = view.data?.storage_locations;
  return found && found.ready === false ? el("p", { class: "sub", text: STORAGE_LOCATIONS_OFF }) : null;
}
