/* Storage locations (E8-S22) and the storage box's count (E8-S19): where a collection row's storage
 * copies are ("Row 2, B", "Binder"), set on the Collection page's card sheet and shown in the Card list
 * and Build decks' pull and put-back steps. Locations are kept apart from the rows (their sha256 stays
 * the eight columns'): the rows answers' "locations" {ready, rows: {colKey: text}} and "storage_box". */
"use strict";

const STORAGE_LOCATION_MAX = 40;
const STORAGE_LOCATION_ROWS = ["Row 1", "Row 2", "Row 3", "Row 4"];
const STORAGE_LOCATIONS_OFF = "Storage locations aren't available yet: Deck Lab's database needs updating on the PC.";
const STORAGE_LOCATION_BATCH_MAX = 50000;
const STORAGE_LOCATION_BODY_MAX = 4 * 1024 * 1024;

/** A locations answer as the page keeps it; null without one (an older server). */
function colLocations(answer) {
  if (!answer || typeof answer !== "object") return null;
  return { ready: answer.ready === true, rows: answer.rows && typeof answer.rows === "object" ? { ...answer.rows } : {},
    sha256: typeof answer.sha256 === "string" && /^[a-f0-9]{64}$/.test(answer.sha256) ? answer.sha256 : null,
    error: typeof answer.error === "string" ? answer.error : "" };
}

/** Take a rows answer's locations and storage box count into the page's view. */
function colTakeLocations(cv, answer) {
  if (!answer) return;
  if (answer.locations) cv.locations = colLocations(answer.locations);
  else if (Array.isArray(answer.rows) && cv.locations) cv.locations = { ...cv.locations, sha256: null };
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
  const elsewhere = box.elsewhere ? ` Cards kept outside the box's rows (${plural(box.elsewhere, "card")}, such as in a binder) aren't counted.` : "";
  const counted = (box.not_counted ? ` Basic lands (${plural(box.not_counted, "card")}) aren't counted.` : "") + elsewhere;
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

/** Location filtering and batches need a checked location snapshot, including on an older server. */
function colLocationsChecked(cv) { return !!(cv.locations?.ready && cv.locations.sha256 && !cv.locations.error); }

function colLocationsWhy(cv) {
  return cv.locations?.ready === false ? STORAGE_LOCATIONS_OFF
    : cv.locations?.error || "Storage locations couldn't be checked. Reload the collection before filtering or changing them.";
}

/** Filter values distinguish an actual location named "none" from No location recorded. */
function colLocationMatches(cv, row) {
  const value = cv.locationFilter || "all";
  if (value === "all") return true;
  if (!colLocationsChecked(cv)) return false;
  const location = colLocationOf(cv, row);
  return value === "none" ? !location : value === `place:${location}`;
}

function colLocationFilterOptions(cv, select) {
  const value = cv.locationFilter || "all";
  const places = new Set(Object.values(cv.locations?.rows || {}).filter(text => typeof text === "string" && text));
  if (value.startsWith("place:")) places.add(value.slice(6)); // retain an exact filter even at zero matches
  clear(select).append(el("option", { value: "all", text: "All locations" }),
    el("option", { value: "none", text: "No location recorded" }),
    ...[...places].sort((a, b) => a.localeCompare(b)).map(text => el("option", { value: `place:${text}`, text })));
  select.value = value;
  select.disabled = cv.busy || !colLocationsChecked(cv);
}

/** The lab toolbar and casual filter sheet share the same state and native-change rollback. */
function colLocationFilter(cv, sheet = null) {
  const select = el("select", { class: "col-location-filter col-mutate", "aria-label": "Storage location", onchange: () => {
    const owner = sheet ? !sheet.closed && sheet.dialog.contains(select)
      && document.querySelector("dialog[open]") === sheet.dialog : cv.root?.contains(select) && !document.querySelector("dialog[open]");
    if (!colActive(cv) || cv.busy || !select.isConnected || select.disabled || !owner || keyboardMenuOpen()
        || !colLocationsChecked(cv)) { select.value = cv.locationFilter || "all"; return; }
    cv.locationFilter = select.value;
    cv.page = 1; cv.casualLimit = COL_CASUAL_ROWS;
    drawColRowList(cv);
  } });
  const hint = el("small", { class: "field-hint col-location-filter-hint" });
  if (!cv.locationFilters) cv.locationFilters = new Map();
  cv.locationFilters.set(select, hint);
  colLocationFilterOptions(cv, select);
  hint.hidden = colLocationsChecked(cv); hint.textContent = hint.hidden ? "" : colLocationsWhy(cv);
  return el("label", { class: "field col-location-filter-field" }, el("span", { text: "Storage location" }), select, hint);
}

function colLocationFiltersSync(cv) {
  for (const [select, hint] of cv.locationFilters || []) {
    if (!select.isConnected) { cv.locationFilters.delete(select); continue; }
    colLocationFilterOptions(cv, select);
    hint.hidden = colLocationsChecked(cv); hint.textContent = hint.hidden ? "" : colLocationsWhy(cv);
  }
}

function colLocationCanWrite(cv) {
  return cv.editable && seesInventory(cv.space) && canEditSpace(cv.space) && colLocationsChecked(cv);
}

/** Separate named scopes use the existing one selection; no copies or inspector selection are added. */
function colLocationBatchTools(cv) {
  if (!cv.editable || !seesInventory(cv.space) || !canEditSpace(cv.space)) return null;
  const make = (selected) => el("button", { type: "button", class: `btn col-mutate col-location-${selected ? "selected" : "shown"}`,
    onclick: event => { if (colBulkActionCurrent(cv, event.currentTarget)) openLocationBatch(cv, selected, event.currentTarget); } });
  cv.locationShownButton = make(false); cv.locationSelectedButton = make(true);
  cv.locationBatchNote = el("p", { class: "sub col-location-batch-note" });
  return el("div", { class: "col-location-actions" }, cv.locationShownButton, cv.locationSelectedButton, cv.locationBatchNote);
}

function colLocationBatchSync(cv, shown) {
  if (!cv.locationShownButton) return;
  const allowed = cv.editable && seesInventory(cv.space) && canEditSpace(cv.space);
  const count = cv.bulkSelected?.size || 0, checked = colLocationsChecked(cv);
  cv.locationShownButton.hidden = !allowed || !shown.length;
  cv.locationSelectedButton.hidden = !allowed || !count;
  cv.locationShownButton.disabled = cv.locationSelectedButton.disabled = cv.busy || !checked;
  cv.locationShownButton.textContent = `Set storage location: ${plural(shown.length, "row")} shown`;
  cv.locationSelectedButton.textContent = `Set storage location: ${num(count)} selected`;
  cv.locationBatchNote.hidden = !allowed || checked;
  cv.locationBatchNote.textContent = checked ? "" : colLocationsWhy(cv);
}

function colLocationSheetCurrent(ctx) {
  return !ctx.busy && !ctx.cv.busy && !ctx.sheet.closed && colActive(ctx.cv) && colLocationCanWrite(ctx.cv)
    && ctx.sheet.dialog.isConnected && document.querySelector("dialog[open]") === ctx.sheet.dialog && !keyboardMenuOpen();
}

/** Both scopes freeze every opened printing key and the two versions the review describes. */
function openLocationBatch(cv, selected = false, opener = null) {
  if (!colActive(cv) || cv.busy || !colLocationCanWrite(cv) || document.querySelector("dialog[open]") || keyboardMenuOpen()) return null;
  const rows = colShownRows(cv).filter(row => !selected || cv.bulkSelected?.has(colBulkKey(row)));
  if (!rows.length) return null;
  if (rows.length > STORAGE_LOCATION_BATCH_MAX) {
    colSay(cv, `A storage-location batch can review at most ${num(STORAGE_LOCATION_BATCH_MAX)} rows. Narrow the search or selection first.`);
    return null;
  }
  const sheet = colOpenSheet("Set storage location"), id = key => `col-location-${key}-${sheet.heading.id}`;
  const ctx = { cv, sheet, selected, opener, busy: false, action: "", text: "", keys: new Set(rows.map(colBulkKey)), rows: [] };
  colLocationBatchCapture(ctx, rows);
  const change = () => {
    if (!colLocationSheetCurrent(ctx)) { ctx.mode.value = ctx.action; ctx.input.value = ctx.text; return; }
    ctx.action = ctx.mode.value; ctx.text = ctx.input.value; drawLocationBatch(ctx);
  };
  ctx.mode = el("select", { id: id("action"), "aria-label": "Location action", onchange: change },
    el("option", { value: "", text: "Choose an action" }), el("option", { value: "assign", text: "Assign one location" }),
    el("option", { value: "clear", text: "Clear recorded locations" }));
  ctx.mode.value = "";
  const choices = el("datalist", { id: id("places") }, colLocationChoices(cv).map(text => el("option", { value: text })));
  ctx.input = el("input", { id: id("place"), type: "text", maxlength: STORAGE_LOCATION_MAX, autocomplete: "off",
    list: choices.id, placeholder: "Such as Row 2, B or Binder", oninput: () => {
      if (colLocationSheetCurrent(ctx) && ctx.input.value) ctx.mode.value = "assign";
      change();
    } });
  ctx.fields = el("fieldset", { class: "col-bulk-fields" },
    el("legend", { class: "sr-only", text: "Location change" }),
    el("label", { class: "field", for: ctx.mode.id }, el("span", { text: "Action" }), ctx.mode),
    el("label", { class: "field", for: ctx.input.id }, el("span", { text: "New storage location" }), ctx.input, choices));
  ctx.message = el("div", { class: "col-sheet-message", role: "status", "aria-live": "polite" });
  ctx.scope = el("p", { class: "sub col-location-scope" });
  ctx.list = el("ul", { class: "col-location-review-list", tabindex: 0, "aria-label": "Reviewed printing rows and locations" });
  ctx.summary = el("p", { class: "col-bulk-summary col-location-summary", role: "status", "aria-live": "polite" });
  sheet.body.append(el("div", { class: "col-form col-location-batch" }, ctx.message, ctx.scope, ctx.fields, ctx.summary, ctx.list));
  drawLocationBatch(ctx);
  return ctx;
}

function colLocationBatchCapture(ctx, rows) {
  ctx.rows = rows.map(colBase);
  ctx.keys = new Set(ctx.rows.map(colBulkKey));
  ctx.before = Object.fromEntries(ctx.rows.map(row => [colBulkKey(row), colLocationOf(ctx.cv, row)]));
  ctx.reviewSha = ctx.cv.sha256; ctx.locationsSha = ctx.cv.locations?.sha256;
}

function colLocationBatchTarget(ctx) {
  if (ctx.action === "clear") return { location: "" };
  if (ctx.action !== "assign") return { error: "Choose a location or explicitly clear recorded locations." };
  if (/[\x00-\x1f\x7f-\x9f]/.test(ctx.text)) return { error: "A storage location is one line, with no control characters." };
  const text = ctx.text.replace(/\s+/g, " ").trim();
  if (!text) return { error: "Enter a location. To remove one, choose Clear recorded locations." };
  if ([...text].length > STORAGE_LOCATION_MAX) return { error: `A storage location is at most ${STORAGE_LOCATION_MAX} characters.` };
  if (/^[=+@-]/.test(text)) return { error: "A storage location can't start with = + - or @." };
  return { location: text };
}

function drawLocationBatch(ctx) {
  const allowed = ctx.cv.editable && seesInventory(ctx.cv.space) && canEditSpace(ctx.cv.space);
  const checked = allowed && colLocationsChecked(ctx.cv), target = colLocationBatchTarget(ctx);
  ctx.scope.hidden = ctx.list.hidden = !allowed;
  ctx.scope.textContent = `For the ${plural(ctx.rows.length, ctx.selected ? "selected row" : "reviewed row")} listed below. `
    + "Only storage locations change; copies, condition, language, notes and deck lists stay as they are.";
  ctx.fields.hidden = !ctx.rows.length || !checked;
  ctx.input.disabled = ctx.busy || ctx.action === "clear";
  clear(ctx.list);
  if (ctx.rows.length) ctx.list.append(...ctx.rows.map(row => {
    const old = ctx.before[colBulkKey(row)] || "No location recorded";
    const next = target.error ? "Choose an action" : target.location || "No location recorded";
    return el("li", { "data-location-key": colBulkKey(row), text:
      `${row.name} (${colPrinting(row)}), ${plural(Number(row.quantity), "copy", "copies")}: ${old} \u2192 ${next}` });
  }));
  const count = target.error ? 0 : ctx.rows.filter(row => ctx.before[colBulkKey(row)] !== target.location).length;
  ctx.summary.textContent = !allowed ? "You can no longer change this collection. Close the review."
    : !checked ? colLocationsWhy(ctx.cv) : !ctx.rows.length
    ? "None of the reviewed rows are still shown. Close this, then choose rows again."
    : target.error || (count ? `${target.location ? "Assigns the location to" : "Clears the location from"} ${plural(count, "row")} in one change.`
      : "Nothing to change: every reviewed row already has this location.");
  const owned = event => event?.currentTarget?.isConnected && ctx.sheet.foot.contains(event.currentTarget);
  sheetActions(ctx.sheet, [
    { text: ctx.rows.length && checked ? "Cancel" : "Close", value: "cancel", onclick: event => { if (owned(event)) ctx.sheet.close(); } },
    ...(!ctx.rows.length || !checked ? [] : [{ text: count ? `Save ${plural(count, "row")}` : "Save", kind: "primary", value: "save",
      disabled: !count || ctx.busy, onclick: event => { if (owned(event)) saveLocationBatch(ctx); } }])]);
}

function colLocationBatchRows(ctx) {
  return colShownRows(ctx.cv).filter(row => ctx.keys.has(colBulkKey(row)) && (!ctx.selected || ctx.cv.bulkSelected?.has(colBulkKey(row))));
}

function colLocationBatchRebase(ctx, words) {
  const previous = ctx.rows.length;
  colLocationBatchCapture(ctx, colLocationBatchRows(ctx));
  clear(ctx.message).append(el("div", { class: "box box-warn", role: "alert" },
    el("p", { text: words || "The collection or its locations changed after this review." }),
    previous > ctx.rows.length ? el("p", { text: `${plural(previous - ctx.rows.length, "reviewed row")} no longer shown ${previous - ctx.rows.length === 1 ? "was" : "were"} left out.` }) : null,
    el("p", { text: "Nothing was saved. No other rows were added. Check the current rows and old/new locations, then save again." })));
  drawLocationBatch(ctx);
}

function colLocationBatchBusy(ctx, busy) {
  ctx.busy = busy; setCollectionBusy(ctx.cv, busy);
  ctx.fields.disabled = busy; ctx.mode.disabled = busy; ctx.input.disabled = busy || ctx.action === "clear";
  for (const button of ctx.sheet.foot.querySelectorAll("button")) button.disabled = busy;
  colLocationFiltersSync(ctx.cv); colLocationBatchSync(ctx.cv, colShownRows(ctx.cv));
}

async function saveLocationBatch(ctx) {
  if (!colLocationSheetCurrent(ctx)) return;
  const cv = ctx.cv, current = colLocationBatchRows(ctx);
  const reviewed = new Map(ctx.rows.map(row => [colBulkKey(row), row]));
  if (cv.sha256 !== ctx.reviewSha || cv.locations.sha256 !== ctx.locationsSha || current.length !== ctx.rows.length
      || current.some(row => !reviewed.has(colBulkKey(row)) || !colSameRow(reviewed.get(colBulkKey(row)), row)
        || ctx.before[colBulkKey(row)] !== colLocationOf(cv, row))) {
    colLocationBatchRebase(ctx); return;
  }
  const target = colLocationBatchTarget(ctx);
  if (target.error || !ctx.rows.some(row => ctx.before[colBulkKey(row)] !== target.location)) return;
  const keys = ctx.rows.map(row => ({ set: row.set, collector_number: row.collector_number, finish: row.finish }));
  const body = { space: cv.space, sha256: ctx.reviewSha, locations_sha256: ctx.locationsSha, keys, location: target.location };
  if (colLocationBodySize({ profile: cv.profile, ...body }) > STORAGE_LOCATION_BODY_MAX) {
    clear(ctx.message).append(el("div", { class: "box box-crit", role: "alert", text:
      "This storage-location batch is too large to send in one change. Close the review and narrow the search or selection." }));
    return;
  }
  colLocationBatchBusy(ctx, true);
  clear(ctx.message).append(loadingBox("Saving storage locations."));
  try {
    const answer = await apiWrite("/api/collection/locations/bulk", body);
    colLocationBatchBusy(ctx, false);
    if (ctx.selected) for (const key of ctx.keys) cv.bulkSelected?.delete(key);
    if (!ctx.sheet.closed) ctx.sheet.close();
    colChanged(cv, answer, answer.changed ? `Storage location saved on ${plural(answer.changed, "row")}.` : "Nothing needed changing.");
    if (colActive(cv) && !document.querySelector("dialog[open]") && !keyboardMenuOpen()) {
      const focused = document.activeElement;
      if (focused === ctx.opener || focused === document.body || !focused?.isConnected) {
        const focus = ctx.opener?.isConnected && !ctx.opener.hidden && !ctx.opener.disabled ? ctx.opener : cv.rowSearch;
        if (focus) focus.focus({ preventScroll: true });
      }
    }
  } catch (error) {
    colLocationBatchBusy(ctx, false);
    if (ctx.sheet.closed || !colActive(cv)) return;
    if (error.status === 409 && Array.isArray(error.data?.rows)) {
      cv.sha256 = error.data.sha256; colTakeRows(cv, error.data);
      if (cv.kind === "rows") drawColRowList(cv);
      colLocationBatchRebase(ctx, error.message);
    } else {
      clear(ctx.message).append(el("div", { class: "box box-crit", role: "alert" }, el("p", { text: error.message })));
      drawLocationBatch(ctx);
    }
  }
}

/** Count JSON's UTF-8 bytes without depending on an optional browser encoder. */
function colLocationBodySize(body) {
  let bytes = 0;
  for (const char of JSON.stringify(body)) {
    const value = char.codePointAt(0);
    bytes += value < 0x80 ? 1 : value < 0x800 ? 2 : value < 0x10000 ? 3 : 4;
  }
  return bytes;
}
