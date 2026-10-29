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
  cv.forecastRevision = (cv.forecastRevision || 0) + 1;
  if (answer) {
    if (answer.locations) cv.locations = colLocations(answer.locations);
    else if (Array.isArray(answer.rows) && cv.locations) cv.locations = { ...cv.locations, sha256: null };
    if (Object.hasOwn(answer, "storage_box")) cv.storageBoxCount = answer.storage_box || null;
  }
  cv.storageForecast = colStorageForecast(answer?.storage_forecast, cv);
  drawColStorageForecast(cv);
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
  drawColStorageForecast(cv);
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

// ---------------------------------------------------- pending storage scenario

const COL_FORECAST_MAX = 1000000000;
const COL_FORECAST_PAGE = 20;
const COL_FORECAST_PROBLEMS = Object.freeze({
  baseline_unavailable: "The current box count could not be checked.",
  locations_unavailable: "Storage locations could not be checked, so box routing is unknown.",
  snapshot_stale: "These are last-snapshot facts; no current occupancy scenario is shown.",
  sources_unavailable: "Some pending delivery sources could not be checked.",
  work_limit: "The checking limit was reached; the known part is incomplete.",
  source_unknown: "Some pending contents are unknown.",
  products_undecided: "Pending products are excluded: whether they stay intact is chosen when received.",
  tokens_excluded: "Token cards are excluded from this storage scenario.",
  holder_shortfall_unknown: "Overlap of these candidates with current holder shortfalls could not be checked.",
  details_omitted: "Some source or printing details are omitted from this answer.",
  invalid_record: "An order record could not be verified.",
  ambiguous_path: "A delivery source is referenced ambiguously.",
  missing_order: "A pending source has no verified order record.",
  product_status: "A product's recorded status could not be verified.",
  product_choice: "Whether this product stays intact is chosen when received.",
  invalid_cards: "The recorded card rows could not be verified.",
  unreadable_source: "The recorded contents could not be read."
});
const COL_FORECAST_NO_ROUTING = ["invalid_record", "ambiguous_path", "missing_order", "product_status",
  "sources_unavailable", "locations_unavailable", "work_limit"];

/** Forecast facts belong only to the original home-record reader and Collection route. */
function colForecastAllowed(cv) {
  return cv.space === HOME_SPACE && state.profile && cv.forecastProfile === state.profile
    && cv.profile === state.profile.id && ownSpace() === HOME_SPACE && state.may?.see_home_records === true
    && seesInventory(HOME_SPACE) && cv.token === routeToken && cv.forecastHash === location.hash
    && parseHash().path === "collection";
}

/** Whitelist, conserve and freeze a bounded answer. Malformed facts retain no source details. */
function colStorageForecast(raw, cv) {
  if (!raw || !colForecastAllowed(cv)) return null;
  const bad = () => Object.freeze({ status: "unknown", unverified: true });
  const count = value => Number.isSafeInteger(value) && value >= 0 && value <= COL_FORECAST_MAX;
  const optional = value => value === null || count(value);
  const text = (value, limit) => typeof value === "string" && value.length <= limit && !/[\x00-\x1f\x7f-\x9f]/.test(value);
  const ident = value => value === null || typeof value === "string" && value.length <= 128 && /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(value);
  const problem = value => value === null || Object.hasOwn(COL_FORECAST_PROBLEMS, value);
  const numeric = ["known_loose_cards", "basic_excluded", "unknown_sources", "omitted_sources"];
  const nullable = ["current_cards", "capacity", "box_candidates", "recorded_elsewhere",
    "possible_current_holder_shortfall", "cards_if_candidates_filed"];
  if (!["ready", "partial", "unknown"].includes(raw.status) || raw.basis !== "known_pending_loose_cards"
      || typeof raw.stale !== "boolean" || numeric.some(key => !count(raw[key])) || nullable.some(key => !optional(raw[key]))
      || raw.capacity === 0 || ![null, true, false].includes(raw.over_if_candidates_filed)
      || !raw.pending_products || !["count", "known_reference_cards", "unknown_contents"].every(key => count(raw.pending_products[key]))
      || !raw.tokens_excluded || !["known_cards", "unknown_components"].every(key => count(raw.tokens_excluded[key]))
      || !Array.isArray(raw.problems) || raw.problems.length > Object.keys(COL_FORECAST_PROBLEMS).length
      || raw.problems.some(value => value === null || !problem(value)) || new Set(raw.problems).size !== raw.problems.length
      || !Array.isArray(raw.sources) || raw.sources.length > 100) return bad();
  if ((raw.box_candidates === null) !== (raw.recorded_elsewhere === null)
      || raw.basic_excluded > raw.known_loose_cards
      || raw.box_candidates !== null && raw.box_candidates + raw.basic_excluded + raw.recorded_elsewhere !== raw.known_loose_cards
      || raw.pending_products.unknown_contents > raw.pending_products.count
      || raw.status === "ready" && (raw.stale || raw.unknown_sources > 0)) return bad();
  if (raw.current_cards !== null && (!cv.storageBoxCount || raw.current_cards !== cv.storageBoxCount.cards
      || raw.capacity !== cv.storageBoxCount.capacity)) return bad();
  if (raw.possible_current_holder_shortfall !== null && raw.box_candidates !== null
      && raw.possible_current_holder_shortfall > raw.box_candidates) return bad();
  const total = raw.current_cards !== null && raw.capacity !== null && raw.box_candidates !== null && !raw.stale
    ? raw.current_cards + raw.box_candidates : null;
  if (total !== raw.cards_if_candidates_filed || total !== null && !count(total)
      || raw.over_if_candidates_filed !== (total === null ? null : total > raw.capacity)) return bad();
  const sources = [], sourceKeys = new Set(), sums = { cards: 0, box: 0, basic: 0, elsewhere: 0,
    products: 0, references: 0, productUnknown: 0, tokens: 0, tokenUnknown: 0, unknown: 0 };
  let detailRows = 0;
  for (const source of raw.sources) {
    if (!source || !["cards", "tokens", "product", "unknown"].includes(source.kind)
        || !ident(source.order_id) || !ident(source.component_id) || typeof source.unknown !== "boolean"
        || !optional(source.known_cards) || !optional(source.box_candidates) || !count(source.basic_excluded)
        || !optional(source.recorded_elsewhere) || !count(source.omitted_rows) || !problem(source.problem)
        || !["Pending cards", "Pending tokens", "Pending product", "Unverified source"].includes(source.label)
        || !Array.isArray(source.rows) || source.rows.length + detailRows > 100) return bad();
    if (source.kind !== "cards" && (source.rows.length || source.basic_excluded || source.box_candidates !== null
        || source.recorded_elsewhere !== null) || source.kind === "unknown" && (!source.unknown || source.known_cards !== null)
        || source.kind === "cards" && source.known_cards === null && (!source.unknown || source.rows.length
          || source.basic_excluded || source.box_candidates !== null || source.recorded_elsewhere !== null)) return bad();
    if (source.order_id && source.component_id) {
      const key = JSON.stringify([source.order_id, source.component_id]);
      if (sourceKeys.has(key)) return bad();
      sourceKeys.add(key);
    }
    if (source.kind === "cards" && source.known_cards !== null) {
      if (source.basic_excluded > source.known_cards || (source.box_candidates === null) !== (source.recorded_elsewhere === null)
          || source.box_candidates !== null && source.box_candidates + source.basic_excluded + source.recorded_elsewhere !== source.known_cards) return bad();
      sums.cards += source.known_cards; sums.basic += source.basic_excluded;
      sums.box += source.box_candidates || 0; sums.elsewhere += source.recorded_elsewhere || 0;
    }
    if (source.kind === "product") { sums.products++; sums.references += source.known_cards || 0; sums.productUnknown += source.known_cards === null ? 1 : 0; }
    if (source.kind === "tokens") { sums.tokens += source.known_cards || 0; sums.tokenUnknown += source.known_cards === null ? 1 : 0; }
    if (source.unknown) sums.unknown++;
    const rows = [];
    for (const row of source.rows) {
      if (!row || !text(row.name, 200) || !row.name || !text(row.set, 8) || !/^[a-z0-9]{2,8}$/.test(row.set)
          || !text(row.collector_number, 40) || !["nonfoil", "foil", "etched"].includes(row.finish)
          || !count(row.quantity) || !row.quantity || !["box", "basic", "elsewhere", "unknown"].includes(row.disposition)
          || !text(row.location, 40)) return bad();
      rows.push(Object.freeze({ name: row.name, set: row.set, collector_number: row.collector_number,
        finish: row.finish, quantity: row.quantity, disposition: row.disposition, location: row.location }));
    }
    detailRows += rows.length;
    const visibleCards = rows.reduce((sum, row) => sum + row.quantity, 0);
    if (source.kind === "cards" && source.known_cards !== null && (visibleCards > source.known_cards
        || source.omitted_rows === 0 && visibleCards !== source.known_cards)) return bad();
    for (const [field, disposition] of [["basic_excluded", "basic"], ["box_candidates", "box"], ["recorded_elsewhere", "elsewhere"]]) {
      const visible = rows.filter(row => row.disposition === disposition).reduce((sum, row) => sum + row.quantity, 0);
      if (source.kind === "cards" && source.known_cards !== null && source[field] !== null
          && (visible > source[field] || !source.omitted_rows && visible !== source[field])) return bad();
    }
    sources.push(Object.freeze({ order_id: source.order_id, component_id: source.component_id, kind: source.kind,
      known_cards: source.known_cards, box_candidates: source.box_candidates, basic_excluded: source.basic_excluded,
      recorded_elsewhere: source.recorded_elsewhere, unknown: source.unknown, problem: source.problem,
      rows: Object.freeze(rows), omitted_rows: source.omitted_rows }));
  }
  const pairs = [["cards", raw.known_loose_cards], ["basic", raw.basic_excluded], ["box", raw.box_candidates],
    ["elsewhere", raw.recorded_elsewhere], ["products", raw.pending_products.count], ["references", raw.pending_products.known_reference_cards],
    ["productUnknown", raw.pending_products.unknown_contents], ["tokens", raw.tokens_excluded.known_cards],
    ["tokenUnknown", raw.tokens_excluded.unknown_components], ["unknown", raw.unknown_sources]];
  if (pairs.some(([key, value]) => value !== null && (sums[key] > value || !raw.omitted_sources && sums[key] !== value))) return bad();
  if ([...raw.problems, ...sources.map(source => source.problem)].some(code => COL_FORECAST_NO_ROUTING.includes(code))
      && (raw.box_candidates !== null || raw.recorded_elsewhere !== null || raw.cards_if_candidates_filed !== null
        || raw.over_if_candidates_filed !== null)) return bad();
  return Object.freeze({ status: raw.status, stale: raw.stale, ...Object.fromEntries([...numeric, ...nullable].map(key => [key, raw[key]])),
    over_if_candidates_filed: raw.over_if_candidates_filed,
    pending_products: Object.freeze({ count: raw.pending_products.count, known_reference_cards: raw.pending_products.known_reference_cards,
      unknown_contents: raw.pending_products.unknown_contents }),
    tokens_excluded: Object.freeze({ known_cards: raw.tokens_excluded.known_cards, unknown_components: raw.tokens_excluded.unknown_components }),
    sources: Object.freeze(sources), problems: Object.freeze([...raw.problems]) });
}

/** Render facts from this answer only; retained controls cannot expand a newer or private answer. */
function drawColStorageForecast(cv) {
  const host = cv.forecastNote;
  if (!host) return;
  if (!colForecastAllowed(cv) || !cv.storageForecast || !cv.root?.isConnected || !cv.root.contains(host)) {
    cv.storageForecast = null; cv.forecastRendered = null; clear(host); host.hidden = true; return;
  }
  const forecast = cv.storageForecast;
  if (cv.forecastRendered === forecast) return;
  cv.forecastRendered = forecast; clear(host); host.hidden = false;
  host.append(el("h2", { text: "Pending deliveries: storage scenario" }));
  if (forecast.unverified) {
    host.append(el("p", { text: "The pending delivery forecast could not be verified. No future occupancy estimate is shown." })); return;
  }
  host.append(el("p", { class: "sub", text: "A conditional scenario for the known loose card copies recorded as pending. "
    + "It assumes those copies remain unsleeved and follow the same printing's recorded location; an unrecorded location means the box. "
    + "This does not predict final occupancy or guarantee that future deliveries will fit." }));
  if (forecast.stale) host.append(el("p", { class: "box box-warn", text: "Last-snapshot facts: pending deliveries and current stock may have changed." }));
  host.append(el("p", { text: `${plural(forecast.known_loose_cards, "known pending card copy", "known pending card copies")}. `
    + (forecast.box_candidates === null ? "How many belong in the box could not be checked."
      : `${plural(forecast.box_candidates, "box candidate", "box candidates")} under these assumptions.`) }));
  if (forecast.cards_if_candidates_filed !== null) host.append(el("p", { text:
    `If only those candidates were filed in the box: about ${num(forecast.cards_if_candidates_filed)} cards against ${num(forecast.capacity)} places. `
    + (forecast.over_if_candidates_filed ? "That conditional scenario exceeds capacity." : "Excluded and unknown deliveries are outside this comparison.") }));
  else host.append(el("p", { text: "No combined occupancy scenario is available from these facts." }));
  const products = forecast.pending_products, tokens = forecast.tokens_excluded;
  host.append(el("ul", {},
    el("li", { text: `Basic lands excluded: ${num(forecast.basic_excluded)} copies, including special basics.` }),
    el("li", { text: forecast.recorded_elsewhere === null ? "Copies following an off-box location: unknown."
      : `Copies following an off-box location: ${num(forecast.recorded_elsewhere)}.` }),
    el("li", { text: `Pending products excluded: ${plural(products.count, "product reference")}, with ${num(products.known_reference_cards)} known reference-list card copies `
      + `and ${plural(products.unknown_contents, "reference with unknown contents", "references with unknown contents")}. Whether they stay intact is chosen when received.` }),
    el("li", { text: `Tokens excluded: ${num(tokens.known_cards)} known physical card copies; ${plural(tokens.unknown_components, "component with unknown quantity", "components with unknown quantities")}.` }),
    el("li", { text: `Unverified sources: ${num(forecast.unknown_sources)}. Their unknown copies are not counted as zero.` })));
  host.append(el("p", { class: "sub", text: forecast.possible_current_holder_shortfall === null
    ? "Overlap of these candidates with current holder shortfalls is unknown; none has been deducted or assigned."
    : `Up to ${num(forecast.possible_current_holder_shortfall)} of these known box candidates overlap current holder shortfalls; none has been deducted or assigned.` }));
  for (const code of forecast.problems) host.append(el("p", { class: "sub", text: COL_FORECAST_PROBLEMS[code] }));
  const details = el("details", {}, el("summary", { text: "Inspect counted sources and exclusions" }));
  const list = el("ol", { "aria-label": "Pending delivery sources and printing copies", tabindex: 0 });
  const count = el("p", { class: "result-count", role: "status" });
  let shown = 0;
  const draw = () => {
    for (const source of forecast.sources.slice(shown, shown + COL_FORECAST_PAGE)) {
      const subject = { cards: "Pending cards", tokens: "Pending tokens", product: "Pending product", unknown: "Unverified source" }[source.kind];
      const name = source.order_id ? `Order ${source.order_id}${source.component_id ? `, ${source.component_id}` : ""}` : "Unmatched source";
      const item = el("li", {}, el("p", { text: `${name}: ${subject}. `
        + (source.known_cards === null ? "Quantity unknown." : `${plural(source.known_cards, source.kind === "product" ? "reference-list card copy" : "recorded copy", source.kind === "product" ? "reference-list card copies" : "recorded copies")}.`) }));
      if (source.problem) item.append(el("p", { class: "sub", text: COL_FORECAST_PROBLEMS[source.problem] }));
      if (source.rows.length) item.append(el("ul", {}, source.rows.map(row => el("li", { text:
        `${row.quantity} \u00d7 ${row.name} (${colPrinting(row)}): `
        + ({ box: "box candidate", basic: "basic land excluded", elsewhere: "off-box location", unknown: "routing unknown" }[row.disposition])
        + (row.location ? ` (${row.location})` : "") }))));
      if (source.omitted_rows) item.append(el("p", { class: "sub", text: `${plural(source.omitted_rows, "printing detail row")} omitted from this answer; source totals include them.` }));
      list.append(item);
    }
    shown = Math.min(shown + COL_FORECAST_PAGE, forecast.sources.length);
    count.textContent = `${shown} of ${plural(forecast.sources.length, "returned source")}.`
      + (forecast.omitted_sources ? ` ${plural(forecast.omitted_sources, "further source")} omitted; aggregate totals include the checked facts.` : "");
    more.hidden = shown >= forecast.sources.length;
  };
  const more = el("button", { type: "button", class: "btn col-forecast-more", text: "Show more sources", onclick: event => {
    if (!colForecastAllowed(cv) || !colActive(cv) || cv.storageForecast !== forecast || cv.forecastRendered !== forecast
        || !host.isConnected || !cv.root.contains(host) || !host.contains(event.currentTarget)
        || !event.currentTarget.isConnected || event.currentTarget.hidden || event.currentTarget.disabled
        || document.querySelector("dialog[open]") || keyboardMenuOpen()) return;
    draw(); if (more.hidden) list.focus({ preventScroll: true });
  } });
  draw(); details.append(list, count, more); host.append(details);
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
