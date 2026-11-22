/* The Collection Storage map: expected loose copies, with a separate physical count for each section. */
"use strict";

const COL_STORAGE_MAP_API = "/api/collection/storage-map";
const COL_STORAGE_MAP_DATE = new Intl.DateTimeFormat(LOCALE, { dateStyle: "medium", timeStyle: "short" });

function drawCollectionStorageMap(data, space, token) {
  const cv = colView(data, space, token, "map");
  cv.mapProfile = state.profile;
  cv.mapHash = location.hash;
  cv.mapSections = Array.isArray(data.sections) ? data.sections : [];
  cv.mapContent = el("div", { class: "col-map-content" });
  cv.root = el("div", { class: "collection-page col-map-page" }, colHead(cv), cv.mapContent);
  $("#main").append(cv.root);
  if (!cv.unsupported && data.space === space) drawStorageMapContent(cv);
  return cv;
}

function storageMapHere(cv) {
  return colActive(cv) && state.profile === cv.mapProfile && location.hash === cv.mapHash;
}

function storageMapCount(quantity) {
  return `${thousands(quantity)} ${quantity === 1 ? "card" : "cards"}`;
}

function storageMapPlace(section) {
  return [section.container, section.place].filter(Boolean).join(" · ");
}

function storageMapGroup(sections) {
  const containers = new Map();
  for (const section of sections) {
    const container = section.container || "Other locations";
    if (!containers.has(container)) containers.set(container, []);
    containers.get(container).push(section);
  }
  return containers;
}

function drawStorageMapContent(cv) {
  const content = clear(cv.mapContent);
  const sections = cv.mapSections;
  const total = sections.reduce((n, section) => n + section.quantity, 0);
  if (!cv.data.ready && !sections.length) {
    content.append(el("p", { class: "box box-info", text: cv.data.message || "The storage map is unavailable." }));
    return;
  }
  const intro = el("section", { class: "panel col-map-overview", "aria-label": "Storage overview" },
    el("div", { class: "col-map-overview-head" },
      el("div", {}, el("h2", { text: "Expected loose cards" }),
        el("p", { class: "sub", text: "Each section is sized by the copies Deck Lab expects to find. Choose a section to check it against the cards you count." })),
      el("strong", { class: "col-map-total", text: storageMapCount(total) })));
  if (total > 0) intro.append(el("div", { class: "col-map-strip", role: "group", "aria-label": "Proportional storage sections" },
    sections.filter(section => section.quantity > 0).map(section => storageMapButton(cv, section, true))));
  if (cv.data.message) intro.append(el("p", { class: "box box-info", text: cv.data.message }));
  if (cv.data.notice) intro.append(el("p", { class: "sub col-map-excluded", text: cv.data.notice }));
  const excluded = cv.data.excluded || [];
  if (excluded.length) intro.append(el("p", { class: "sub col-map-excluded",
    text: "Outside this map · " + excluded.map(item =>
      item.quantity == null ? item.label : `${item.label} (${storageMapCount(item.quantity)})`).join(" · ") }));
  content.append(intro);
  if (!sections.length) {
    content.append(el("p", { class: "box box-info", text: "There are no recorded sections to audit." }));
    return;
  }
  for (const [container, items] of storageMapGroup(sections)) {
    const populated = items.filter(section => section.quantity > 0 || section.audit);
    const empty = items.filter(section => section.quantity === 0 && !section.audit);
    const buttons = list => el("ul", { class: "col-map-sections" },
      list.map(section => el("li", {}, storageMapButton(cv, section, false))));
    content.append(el("section", { class: "col-map-container" },
      el("div", { class: "col-map-container-head" }, el("h3", { text: container }),
        el("span", { class: "sub", text: storageMapCount(items.reduce((n, section) => n + section.quantity, 0)) })),
      populated.length ? buttons(populated) : null,
      empty.length ? el("details", { class: "col-map-empty" },
        el("summary", { text: `Empty sections (${thousands(empty.length)})` }), buttons(empty)) : null));
  }
}

function storageMapAuditStatus(audit) {
  if (!audit) return "Never audited";
  if (audit.current === false) return "Changed since audit";
  return audit.mismatch_rows || audit.extra ? "Differences found" : "Count matched";
}

function storageMapButton(cv, section, segment) {
  const name = el("span", { class: "col-map-section-name", text: section.label });
  const count = el("span", { class: "col-map-section-count", text: storageMapCount(section.quantity) });
  const status = section.auditable === false ? "Audit unavailable" : storageMapAuditStatus(section.audit);
  const button = el("button", { type: "button", class: segment ? "col-map-segment" : "col-map-section",
    "data-colour": section.colour, "data-section": section.id,
    "aria-label": [storageMapPlace(section), section.label, count.textContent].filter(Boolean).join(", ") +
      (segment ? "" : `, ${status}`),
    title: segment ? [storageMapPlace(section), section.label, count.textContent].filter(Boolean).join(" · ") : null,
    tabindex: segment ? "-1" : null,
    onclick: event => openStorageMapSection(cv, section, event.currentTarget) },
  segment ? [name, count] : [
    el("span", { class: "col-map-swatch", "aria-hidden": true }),
    el("span", { class: "col-map-section-text" }, name,
      section.place && section.place !== section.label ? el("span", { class: "sub", text: section.place }) : null),
    el("span", { class: "col-map-section-facts" }, count, el("span", { class: "sub", text: status })),
  ]);
  if (segment) button.style.flexGrow = section.quantity;
  return button;
}

function storageMapSheetHere(ctx) {
  return storageMapHere(ctx.cv) && !ctx.sheet.closed && ctx.sheet.dialog.getAttribute("open") !== null && ctx.content.isConnected;
}

function openStorageMapSection(cv, section, trigger) {
  if (!storageMapHere(cv) || cv.busy || cv.mapSheet || !trigger.isConnected ||
      !cv.mapContent.contains(trigger) || !cv.mapSections.includes(section)) return;
  const sheet = colOpenSheet(section.label, { wide: true, onClose: () => {
    cv.mapSheet = null;
    if (!storageMapHere(cv)) return;
    if (trigger.isConnected) trigger.focus();
    else [...cv.mapContent.querySelectorAll(".col-map-section")]
      .find(button => button.dataset.section === section.id)?.focus();
  } });
  cv.mapSheet = sheet;
  const ctx = { cv, sheet, id: section.id, busy: false,
    status: el("div", { class: "col-sheet-message", "aria-live": "polite" }),
    content: el("div", { class: "col-map-detail" }) };
  sheet.body.append(ctx.status, ctx.content);
  sheet.beforeDismiss = () => !ctx.busy;
  loadStorageMapSection(ctx);
  return ctx;
}

function storageMapSheetActions(ctx, ...items) {
  const actions = [{ text: "Close", value: "close", onclick: () => ctx.sheet.dismiss(), disabled: ctx.busy }, ...items];
  sheetActions(ctx.sheet, actions.filter(Boolean).map(action => ({ ...action, onclick: event => {
    if (storageMapSheetHere(ctx) && !ctx.busy && event.currentTarget.isConnected && ctx.sheet.foot.contains(event.currentTarget)) action.onclick();
  } })));
}

function storageMapReport(ctx, message, kind = "warn") {
  clear(ctx.status);
  if (message) ctx.status.append(el("p", { class: `box box-${kind}`, role: "status", text: message }));
}

function storageMapDetailPath(ctx) {
  return colPath(COL_STORAGE_MAP_API, ctx.cv.space, new URLSearchParams({ section: ctx.id }));
}

async function loadStorageMapSection(ctx) {
  clear(ctx.status);
  clear(ctx.content).append(loadingBox("Loading section…", { small: true }));
  storageMapSheetActions(ctx);
  try {
    const data = await api(storageMapDetailPath(ctx));
    if (!storageMapSheetHere(ctx)) return;
    if (data.space !== ctx.cv.space || data.section?.id !== ctx.id) throw new Error("This section is unavailable.");
    ctx.data = data;
    drawStorageMapDetail(ctx);
  } catch (error) {
    if (!storageMapSheetHere(ctx)) return;
    clear(ctx.content);
    storageMapReport(ctx, error.message, "crit");
    storageMapSheetActions(ctx, { text: "Try again", value: "retry", onclick: () => loadStorageMapSection(ctx) });
  }
}

function drawStorageMapDetail(ctx) {
  const { section, rows, ready, editable, expect, message } = ctx.data;
  const canAudit = ready && editable && ctx.cv.editable && section.auditable !== false && expect && Array.isArray(rows);
  ctx.sheet.heading.textContent = section.label;
  clear(ctx.content).append(
    el("p", { class: "sub", text: [storageMapPlace(section), `${storageMapCount(section.quantity)} expected`].filter(Boolean).join(" · ") }),
    storageMapAuditHistory(section.audit));
  if (message) storageMapReport(ctx, message, "info");
  if (!canAudit && rows?.length && !ctx.saved) ctx.content.append(
    el("h3", { text: "Expected cards" }),
    el("ul", { class: "col-map-differences" }, rows.map(row => el("li", {}, storageMapRowIdentity(row),
      el("span", { class: "sub", text: storageMapExpected(row) })))));
  storageMapSheetActions(ctx, canAudit ? { text: "Start audit", value: "start", kind: "primary",
    onclick: () => startStorageMapAudit(ctx) } : null);
}

function storageMapAuditHistory(audit) {
  if (!audit) return el("p", { text: "This section has never been audited." });
  const when = new Date(audit.audited_at);
  const date = audit.audited_at && Number.isFinite(when.valueOf())
    ? el("time", { datetime: audit.audited_at, text: COL_STORAGE_MAP_DATE.format(when) }) : "Date unavailable";
  return el("section", { class: "col-map-history" },
    el("h3", {}, "Last audited ", date),
    audit.current === false ? el("p", { class: "box box-warn", text: "The expected contents have changed since this audit." }) : null,
    storageMapAuditSummary(audit),
    storageMapDifferenceList(audit.differences));
}

function storageMapAuditSummary(audit) {
  const found = `${storageMapCount(audit.observed)} counted · ${storageMapCount(audit.expected)} expected`;
  if (!audit.mismatch_rows && !audit.extra) return el("p", { text: `${found}. The count matched.` });
  const changes = [
    audit.missing ? `${storageMapCount(audit.missing)} missing` : null,
    audit.surplus ? `${storageMapCount(audit.surplus)} over the listed counts` : null,
    audit.extra ? `${storageMapCount(audit.extra)} unlisted` : null,
  ].filter(Boolean);
  return el("p", { text: `${found}. ${changes.length ? changes.join(" · ") + "." : "Differences found."}` });
}

function storageMapRowPrinting(row) {
  if (!row.set) return row.description || colPrinting(row);
  const finish = row.finish === "nonfoil" ? "Non-foil" : null;
  return [colPrinting(row), finish, row.description].filter(Boolean).join(" · ");
}

function storageMapRowIdentity(row) {
  return el("span", {}, el("strong", { text: row.name }),
    el("span", { class: "sub", text: [storageMapRowPrinting(row), row.location].filter(Boolean).join(" · ") }));
}

function storageMapExpected(row) {
  return `${thousands(row.quantity)} expected${row.estimated ? " (estimate)" : ""}`;
}

function storageMapDifferenceList(rows) {
  if (!rows?.length) return null;
  return el("ul", { class: "col-map-differences" }, rows.map(row => el("li", {},
    el("span", {}, el("strong", { text: row.name }), " · ", storageMapRowPrinting(row)),
    el("span", { class: "sub", text: `${row.expected} expected · ${row.observed} counted` }))));
}

function storageMapInput(label) {
  return el("input", { type: "text", inputmode: "numeric", autocomplete: "off", "aria-label": label });
}

function startStorageMapAudit(ctx) {
  const { rows, section } = ctx.data;
  ctx.inputs = rows.map((row, index) => {
    const input = storageMapInput(`Counted for ${row.name}, ${storageMapRowPrinting(row)}`);
    const expected = el("span", { id: `${ctx.sheet.heading.id}-expected-${index}`,
      class: "col-map-expected", text: storageMapExpected(row) });
    input.setAttribute("aria-describedby", expected.id);
    return { row, input, expected };
  });
  ctx.extra = storageMapInput("Unlisted cards counted");
  ctx.extra.value = "0";
  const list = el("ul", { class: "col-map-counts" }, ctx.inputs.map(({ row, input, expected }) =>
    el("li", {}, el("label", { class: "col-map-count-row" }, storageMapRowIdentity(row), expected, input))));
  const fill = el("button", { type: "button", class: "btn btn-secondary", text: "Unentered counts match",
    onclick: event => {
      if (!storageMapSheetHere(ctx) || !ctx.form.isConnected || !ctx.form.contains(event.currentTarget)) return;
      for (const { row, input } of ctx.inputs) if (!input.value.trim()) input.value = String(row.quantity);
      storageMapReport(ctx, "Blank counts filled with the expected quantities. Review your counts before saving.", "info");
    } });
  ctx.form = el("div", { class: "col-map-audit-form" },
    el("p", { class: "col-map-instructions", tabindex: "-1",
      text: `Count the cards in ${section.label} by printing and finish. Enter 0 for missing cards.` }),
    storageMapPlace(section) ? el("p", { class: "sub", text: storageMapPlace(section) }) : null,
    rows.some(row => row.estimated) ? el("p", { class: "sub",
      text: "Some expected counts are estimates because Deck Lab cannot establish exactly which copies are held elsewhere." }) : null,
    rows.length ? [el("div", { class: "actions" }, fill), list] : el("p", { class: "sub", text: "Deck Lab expects this section to be empty." }),
    el("label", { class: "col-map-count-row col-map-extra" },
      el("span", {}, el("strong", { text: "Unlisted cards" }),
        el("span", { class: "sub", text: "Copies of cards or printings missing from this list." })), ctx.extra));
  editStorageMapAudit(ctx);
}

function editStorageMapAudit(ctx) {
  storageMapReport(ctx, null);
  clear(ctx.content).append(ctx.form);
  storageMapSheetActions(ctx, { text: "Review count", value: "review", kind: "primary", onclick: () => reviewStorageMapAudit(ctx) });
  ctx.sheet.body.scrollTop = 0;
  ctx.form.querySelector(".col-map-instructions").focus();
}

function storageMapReadCount(input) {
  const value = input.value.trim();
  const quantity = Number(value);
  if (/^\d+$/.test(value) && Number.isSafeInteger(quantity)) return quantity;
  input.focus();
  input.scrollIntoView?.({ block: "nearest" });
  return null;
}

function reviewStorageMapAudit(ctx) {
  const counts = [];
  const differences = [];
  for (const { row, input } of ctx.inputs) {
    const observed = storageMapReadCount(input);
    if (observed === null) return storageMapReport(ctx, "Enter a whole number of zero or more for every printing.");
    counts.push([row.key, observed]);
    if (observed !== row.quantity) differences.push({ ...row, expected: row.quantity, observed });
  }
  const extra = storageMapReadCount(ctx.extra);
  if (extra === null) return storageMapReport(ctx, "Enter a whole number of zero or more for unlisted cards.");
  const observed = counts.reduce((n, [, quantity]) => n + quantity, extra);
  if (!Number.isSafeInteger(observed)) return storageMapReport(ctx, "The total is too large. Check the counts you entered.");
  const audit = { expected: ctx.data.section.quantity, observed,
    mismatch_rows: differences.length, extra, differences,
    missing: differences.reduce((n, row) => n + Math.max(0, row.expected - row.observed), 0),
    surplus: differences.reduce((n, row) => n + Math.max(0, row.observed - row.expected), 0) };
  storageMapReport(ctx, null);
  const heading = el("h3", { text: "Review your count", tabindex: "-1" });
  add(clear(ctx.content), [heading, storageMapAuditSummary(audit), storageMapDifferenceList(differences),
    el("p", { class: "sub", text: "Saving records the audit and its differences. Use the Card list or Tokens page to correct inventory quantities." })]);
  storageMapSheetActions(ctx, { text: "Edit count", value: "edit", onclick: () => editStorageMapAudit(ctx) },
    { text: "Save audit", value: "save", kind: "primary", onclick: () => saveStorageMapAudit(ctx, counts, extra) });
  heading.focus();
}

async function saveStorageMapAudit(ctx, counts, extra) {
  ctx.busy = true;
  storageMapReport(ctx, "Saving audit…", "info");
  for (const button of ctx.sheet.foot.querySelectorAll("button")) button.disabled = true;
  const { cv, id } = ctx;
  try {
    const data = await apiWrite(COL_STORAGE_MAP_API, { space: cv.space, section: id, expect: ctx.data.expect,
      counts: Object.fromEntries(counts), extra });
    if (!storageMapSheetHere(ctx)) return;
    if (data.section?.id !== id) throw new Error("The audit could not be confirmed. Reload this section to check.");
    ctx.busy = false;
    ctx.saved = true;
    cv.mapSections = cv.mapSections.map(section => section.id === id ? data.section : section);
    ctx.data = { ...ctx.data, section: data.section, expect: null };
    drawStorageMapContent(cv);
    drawStorageMapDetail(ctx);
    storageMapReport(ctx, "Audit saved.", "good");
  } catch (error) {
    if (!storageMapSheetHere(ctx)) return;
    ctx.busy = false;
    if (error.status === 409) {
      storageMapReport(ctx, `${error.message} Reload this section to start a new count.`);
      storageMapSheetActions(ctx, { text: "Reload section", value: "reload", kind: "primary", onclick: () => loadStorageMapSection(ctx) });
    } else {
      storageMapReport(ctx, error.message, "crit");
      for (const button of ctx.sheet.foot.querySelectorAll("button")) button.disabled = false;
    }
  }
}
