/* A saved storage discrepancy opens the ordinary inventory tools with a way back to its section. */
"use strict";

let storageAuditCorrection = null;
const STORAGE_AUDIT_TOKEN_FIELDS = ["front", "back", "set", "front_collector_number", "back_collector_number",
  "finish", "front_details", "back_details"];

function storageAuditCorrectionKind(row) {
  if (!row || typeof row.key !== "string" || !Number.isSafeInteger(row.expected) || !Number.isSafeInteger(row.observed)
      || row.expected === row.observed || row.expected < 0 || row.observed < 0) return null;
  if (row.key.startsWith("token-")) {
    return row.token?.front && STORAGE_AUDIT_TOKEN_FIELDS.every(key => typeof row.token[key] === "string") ? "token" : null;
  }
  return row.name && row.set && row.collector_number && ["nonfoil", "foil", "etched"].includes(row.finish) &&
    row.key === colKey(row) ? "card" : null;
}

function storageAuditCorrectionScope(space) {
  return Boolean(state.profile?.id) && space === ownSpace() && seesInventory(space) && canEditSpace(space);
}

function openStorageAuditCorrection(ctx, row) {
  const kind = storageAuditCorrectionKind(row), { cv, sheet, id } = ctx;
  const section = ctx.data?.section;
  if (!kind || !section?.audit?.differences?.includes(row) || ctx.busy || cv.busy || !storageMapSheetHere(ctx) ||
      !storageAuditCorrectionScope(cv.space) || [...document.querySelectorAll("dialog[open]")].at(-1) !== sheet.dialog) return;
  const profile = state.profile, origin = location.hash;
  const destination = kind === "card" ? colHash(cv.space, "rows") : colPath("#/tokens", cv.space);
  const here = () => storageMapHere(cv) && state.profile === profile && storageAuditCorrectionScope(cv.space) &&
    location.hash === origin && ctx.data?.section === section;
  boxCollectionAfterSheet(sheet, here, () => {
    storageAuditCorrection = { kind, profile, space: cv.space, origin, destination, id, label: section.label,
      difference: { ...row, token: row.token ? { ...row.token } : null }, token: null, returning: false };
    location.hash = destination;
  });
}

function storageAuditCorrectionRoute(token) {
  const correction = storageAuditCorrection;
  if (!correction) return;
  const { origin, destination, space, profile } = correction;
  if (state.profile !== profile || !storageAuditCorrectionScope(space)) {
    storageAuditCorrection = null;
  } else if (location.hash === destination && !correction.returning) {
    correction.token = token;
  } else if (location.hash === origin && correction.token !== null) {
    correction.token = token;
    correction.returning = true;
  } else storageAuditCorrection = null;
}

function storageAuditCorrectionCurrent(correction, route) {
  return correction && storageAuditCorrection === correction && correction.profile === state.profile &&
    correction.token === routeToken && location.hash === route && storageAuditCorrectionScope(correction.space);
}

function restoreStorageAuditCorrection(cv) {
  const correction = storageAuditCorrection;
  if (!correction?.returning || !storageAuditCorrectionCurrent(correction, correction.origin) ||
      cv.token !== correction.token || cv.space !== correction.space || !storageMapHere(cv)) return;
  storageAuditCorrection = null;
  const section = cv.mapSections.find(item => item.id === correction.id);
  const trigger = [...cv.mapContent.querySelectorAll(".col-map-section")].find(button => button.dataset.section === correction.id);
  if (!section || !trigger) {
    cv.message.append(el("p", { class: "box box-warn", text: "This audited section is no longer in the Storage map." }));
    return;
  }
  for (let details = trigger.closest("details"); details && cv.mapContent.contains(details);
    details = details.parentNode?.closest("details")) details.setAttribute("open", "");
  openStorageMapSection(cv, section, trigger);
}

function storageAuditPageCorrection(view, kind) {
  const correction = storageAuditCorrection;
  if (correction?.kind !== kind || correction.returning || correction.token !== view.token ||
      correction.space !== view.space || view.data.space !== view.space ||
      !storageAuditCorrectionCurrent(correction, correction.destination)) return null;
  return correction;
}

function storageAuditCorrectionBack(kind) {
  const correction = storageAuditCorrection;
  return correction?.kind === kind && storageAuditCorrectionCurrent(correction, correction.destination)
    ? [correction.origin, "Back to audit"] : undefined;
}

function storageAuditCorrectionPanel(correction, view, content) {
  if (!view.auditPanel) {
    view.auditPanel = el("section", { class: "box box-info col-audit-correction", "aria-label": "Storage audit difference" });
    view.root.insertBefore(view.auditPanel, view.message);
  }
  const active = document.activeElement;
  const previous = view.auditPanel.contains(active) ? active.textContent : null;
  const row = correction.difference;
  clear(view.auditPanel).append(
    el("p", {}, el("strong", { text: correction.label }), " · ",
      row.manualLabel || [row.name, colPrinting(row), row.finish === "nonfoil" ? "Non-foil" : null].filter(Boolean).join(" · ")),
    el("p", { text: `${row.expected} expected${row.estimated ? " (estimate)" : ""} · ${row.observed} counted` }),
    el("p", { text: "Check the printing and finish, nearby sections, packed cards and loans before editing owned copies." }),
    content,
    el("p", {}, el("a", { class: "btn btn-quiet", href: correction.origin, text: "Back to audit" })));
  if (previous) {
    const control = [...view.auditPanel.querySelectorAll("button, a")].find(node => node.textContent === previous);
    (control || view.auditPanel.querySelector("a"))?.focus({ preventScroll: true });
  }
}

function drawStorageAuditCollectionCorrection(cv) {
  const correction = storageAuditPageCorrection(cv, "card");
  if (!correction || !cv.editable || cv.unsupported || cv.auditRows === cv.rows) return;
  cv.auditRows = cv.rows;
  const difference = correction.difference;
  const getRow = () => (cv.rows || []).find(row => colKey(row) === difference.key);
  const row = getRow();
  const here = () => colActive(cv) && cv.editable && storageAuditCorrectionCurrent(correction, correction.destination);
  const action = (label, run) => el("button", { type: "button", class: "btn col-mutate", text: label,
    "aria-haspopup": "dialog", onclick: event => {
      if (here() && !cv.busy && cv.auditPanel.contains(event.currentTarget) && !document.querySelector("dialog[open]")) {
        run(event.currentTarget);
      }
    } });
  const open = target => openCollectionSheet(cv, target, { name: difference.name, audit: { here, printing: difference } });
  storageAuditCorrectionPanel(correction, cv, row ?
    el("div", {},
      el("p", { text: `Total owned: ${num(row.quantity)} · ${colStorageWords(cv, row)}` }),
      el("div", { class: "actions" },
        action("Review owned total", () => { const target = getRow(); if (target) open(target); }),
        colLocationCanWrite(cv) ? action("Review storage location", trigger => {
          const target = getRow(); if (target) openLocationBatch(cv, false, trigger, target);
        }) : null)) :
    el("div", {}, el("p", { text: "This exact printing and finish are no longer listed or have yet to be added." }),
      difference.observed > difference.expected ? action("Add this printing", () => { if (!getRow()) open(null); }) : null));
}

function drawStorageAuditTokenCorrection(view) {
  const correction = storageAuditPageCorrection(view, "token");
  if (!correction || !view.canEdit || view.auditRows === view.data.rows) return;
  view.auditRows = view.data.rows;
  const identity = tokIdentity(correction.difference.token);
  const matching = () => (view.data.rows || []).filter(row => tokIdentity(row) === identity);
  const rows = matching();
  const here = () => tokensActive(view) && view.canEdit && storageAuditCorrectionCurrent(correction, correction.destination);
  const open = (row, event) => {
    if (here() && !view.busy && view.auditPanel.contains(event.currentTarget) && matching().includes(row) &&
        !document.querySelector("dialog[open]")) editToken(view, row, { here, refresh: () => refreshTokens(view) });
  };
  storageAuditCorrectionPanel(correction, view, rows.length === 0 ?
    el("p", { text: "This physical token record has changed or is missing. Check both faces against the Tokens list." }) :
    el("div", {},
      rows.length > 1 ? el("p", { text: "Several rows share these recorded faces and printing. Check the physical card and identify its row first." }) : null,
      el("ul", {}, rows.map(row => el("li", {},
        el("p", { text: [`Total owned: ${num(row.quantity)}`, row.notes].filter(Boolean).join(" · ") }),
        el("button", { type: "button", class: "btn tok-mutate", text: "Review owned total", "aria-haspopup": "dialog",
          "aria-label": rows.length > 1 ? `Review owned total, ${num(row.quantity)} recorded${row.notes ? `, ${row.notes}` : ""}` : null,
          onclick: event => open(row, event) }))))));
}
