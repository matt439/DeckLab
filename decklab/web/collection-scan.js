/* The Collection page's "Scan cards…" (E7-S32): photograph one card at a time with the phone's camera (the file
 * input's capture, which works on http and https alike), shrink the photo on a canvas to at most COL_SCAN_SIDE
 * pixels on its long side and send it as a JPEG to POST /api/collection/scan, which reads it on the PC and answers
 * the printings it may be (nothing is written). A card whose name and bottom line (set code and number) name one
 * printing goes straight onto the pending list (with the others offered instead); when only the name or only the
 * bottom line was read, or reprints share the number read, the visitor picks the printing, or types the card's
 * name and picks from its printings (/api/printings). Each pending card's printing can be changed there: a choice of
 * the printings the scan proposed for its name (or the typed name's), and "Other printings…", the shared printing picker
 * (cards-ui.js pickPrinting) for the card's others. Its copies, finish, condition and language can be changed too
 * (condition is never guessed; language is the one read off the card, else not recorded, never assumed English).
 * A change that makes two pending cards the same printing, finish, condition and language joins them. "Review" turns the list into a collection-columns CSV and hands it to the
 * Import cards sheet's preview (collection.js, previewImport), so the scan is added as an import is: previewed,
 * then one change with its raw import kept. Until it's imported the import sheet offers "Back to the scanned
 * list" (colScanBack), which reopens this sheet with the same pending cards. Photos are never kept. Shared with
 * collection.js (openScanSheet, colScanBack). When the view says this server can't read photos (its scan.available
 * is false: no OCR engine on the PC, collection.scan_flag), the sheet says so and offers only the typed name. */
"use strict";

const COL_SCAN_SIDE = 2000;             // pixels on a photo's long side (decklab/design/scanning-spike.md)
const COL_SCAN_QUALITY = 0.85;          // JPEG quality of the photo sent
const COL_SCAN_MAX = 4 * 1024 * 1024;   // bytes: the server's limit (collection_scan.MAX_PHOTO)
const COL_SCAN_CHOICES = 8;             // initial choices and retained proposals per unresolved photo
const COL_SCAN_UNSURE_MAX = 50;         // bounded proposal metadata only; never photo bytes
const COL_AUDIT_UNLISTED_MAX = 2000;    // distinct unlisted printings and finishes in a storage audit
const COL_SCAN_OFF = "Photos can't be read on this server, so type each card's name instead.";

/** One collection entry sends each method to its existing editor or review. */
function openCollectionAddSheet(cv) {
  if (!colActive(cv) || cv.busy || !cv.editable || cv.unsupported) return null;
  const profile = state.profile, hash = location.hash;
  const current = () => state.profile === profile && location.hash === hash && colActive(cv)
    && !cv.busy && cv.editable && !cv.unsupported;
  const sheet = colOpenSheet("Add cards", {wide: true});
  const choose = (text, help, open) => el("li", {},
    el("button", {type: "button", class: "btn", text, "aria-haspopup": "dialog", onclick: event => {
      if (sheet.closed || keyboardDialog() !== sheet.dialog || !current() || !event.currentTarget.isConnected) return;
      boxCollectionAfterSheet(sheet, current, () => open(cv));
    }}), el("span", {class: "lib-start-line", text: help}));
  sheet.body.append(
    el("p", {text: "Start with a small pile. Keep recorded copies separate so each one is entered once."}),
    el("ul", {class: "lib-start-ways"},
      choose("Enter one", "Choose a printing and the number of identical copies to add.", openCollectionSheet),
      choose("Scan", scanAvailable(cv.data)
        ? "Use a camera, image files or typed names. Check the printings and review the batch together."
        : "Photo reading is unavailable on this server. Type names and review the batch together.", openScanSheet),
      choose("Import a list", "Preview a collection export, typed list or a saved pending batch.", openImportSheet),
      choose("Add a precon", "Check the published list against the precon you own before adding its cards.", openPreconSheet)));
  sheetActions(sheet, [{text: "Close", value: "cancel", onclick: () => sheet.close()}]);
  return sheet;
}

/** Whether the server can read photos: false only when a view says so (an older server's says nothing). */
function scanAvailable(data) {
  return !(data && data.scan && data.scan.available === false);
}

/** Confirm a user dismissal without replacing the scan form or losing its unsaved inputs. */
function guardScanBatch(sheet, here, describe, saving) {
  const route = location.hash, title = sheet.heading.textContent;
  let question, buttons, previous;
  function keep() {
    if (!here() || location.hash !== route) { sheet.close(); return; }
    question.remove(); buttons.remove(); question = null;
    sheet.heading.textContent = title;
    sheet.body.hidden = sheet.foot.hidden = false;
    (previous && sheet.dialog.contains(previous) ? previous : sheet.dialog.querySelector(".sheet-close")).focus();
  }
  sheet.beforeDismiss = () => {
    if (!here() || location.hash !== route) return true;
    if (saving?.()) return false;
    if (question) { keep(); return false; }
    const description = describe();
    if (!description) return true;
    previous = document.activeElement;
    sheet.heading.textContent = "Discard this batch?";
    sheet.body.hidden = sheet.foot.hidden = true;
    const note = el("p", {text: description});
    question = el("div", {class: "sheet-body"}, note);
    const retain = el("button", {type: "button", class: "btn btn-primary", text: "Keep scanning", onclick: keep});
    buttons = el("div", {class: "sheet-foot"}, retain,
      el("button", {type: "button", class: "btn btn-discard", text: "Discard batch", onclick: () => {
        // A photo may have finished while the question was open. Show the updated count first.
        const latest = here() && describe();
        if (latest && latest !== note.textContent) { note.textContent = latest; retain.focus(); return; }
        sheet.close();
      }}));
    sheet.body.parentNode.append(question, buttons);
    retain.focus();
    return false;
  };
}

function scanBatchDescription(rows, label, unresolved = 0) {
  const count = rows.reduce((total, row) => total + row.quantity, 0);
  const parts = [count ? plural(count, label) : "", unresolved ? plural(unresolved, "unresolved photo") : ""].filter(Boolean);
  return parts.length ? `This batch contains ${parts.join(" and ")}. Discarding it clears the batch.` : "";
}

/** Open the sheet (where the visitor may change this collection), with the pending cards brought back from
 * the import sheet, if any. Returns its context, or null. */
function openScanSheet(cv, pending = [], scanStartedAt = Date.now()) {
  if (!colActive(cv) || cv.busy || !cv.editable || cv.unsupported) return null;
  return openCardScan(cv, null, pending, scanStartedAt);
}

/** A physical count belongs to the page that supplies its expectation and reviews its observations. */
function openAuditScan(target) {
  if (!state.profile || !target.current() || target.space !== ownSpace()) return null;
  return openCardScan(null, target, [], Date.now());
}

/** Reuse exact-printing lookup to identify the extras from a hand count. */
function openStorageAuditUnlisted({ space, rows, excludedNames, initial = [], current, finish }) {
  if (!state.profile || !current() || space !== ownSpace()) return null;
  const listed = new Set(rows.filter(row => !row.key?.startsWith("token-")).map(colKey));
  const excluded = new Set(excludedNames);
  const target = {
    title: "Identify unlisted printings", space, current, scan: { available: false },
    instructions: "Look up the exact printing and finish of each unlisted card. Count unidentified cards separately.",
    unlisted: { listed, excluded },
    finish(pending, _skipped, ctx) {
      if (!Number.isSafeInteger(pending.reduce((total, row) => total + row.quantity, 0))) {
        colScanSay(ctx, "warn", "The total is too large. Check the counts you entered.");
        return;
      }
      const result = pending.map(({ name, set, collector_number, finish, quantity, choices }) =>
        ({ name, set, collector_number, finish, quantity, choices }));
      ctx.afterClose = () => { if (ctx.current()) finish(result); };
      ctx.sheet.close();
    },
  };
  return openCardScan(null, target, initial.map(row => ({ ...row, condition: "", language: "" })), Date.now());
}

function openCardScan(cv, audit, pending, scanStartedAt) {
  const viewer = state.profile, token = routeToken, route = location.hash, space = audit ? audit.space : cv.space;
  const current = audit ? () => state.profile === viewer && routeToken === token && location.hash === route && audit.current()
    : () => colActive(cv) && cv.profile === viewer.id && cv.space === space && cv.editable && !cv.unsupported && !cv.busy;
  const sheet = colOpenSheet(audit ? audit.title : `Scan cards into ${colWhose(space)}`, { wide: true,
    onClose: () => {
      document.removeEventListener("visibilitychange", refreshOnReturn);
      ctx.captureRead?.controller.abort(); ctx.live?.stop(); ctx.grid?.stop();
      ctx.afterClose?.();
    } });
  const id = (key) => `col-scan-${key}-${sheet.heading.id}`;
  const ctx = { cv, audit, current, sheet, pending: colScanCopy(pending), busy: false, picking: false, seq: 0, last: null,
    reads: scanAvailable(audit ? {scan: audit.scan} : cv.data), defaults: {condition: "", language: "", finish: ""},
    unsure: [], nextPhoto: 0, currentUnsure: null, resolving: null, skipped: 0, auditReview: false, nameOnly: audit?.mode === "deck",
    space, route, scanStartedAt };
  guardScanBatch(sheet, () => colScanHere(ctx), () => audit?.unlisted
    ? (JSON.stringify(ctx.pending) === JSON.stringify(pending) ? "" : "Discarding returns to your previous choice of unlisted printings.")
    : scanBatchDescription(ctx.pending, "card", ctx.unsure.length)
      || (ctx.skipped ? `Discarding this audit clears ${plural(ctx.skipped, "skipped photo")}.` : audit?.manualDescription?.()));
  ctx.input = el("input", { id: id("photo"), type: "file", accept: "image/*", capture: "environment", class: "col-file" });
  ctx.input.addEventListener("change", () => {
    const file = ctx.input.files && ctx.input.files[0];
    if (file && colScanControlHere(ctx, ctx.input)) scanPhoto(ctx, file);
  });
  ctx.name = el("input", { id: id("name"), type: "text", autocomplete: "off", spellcheck: "false",
    placeholder: "The card's exact name" });
  ctx.name.addEventListener("input", () => {
    if (!ctx.lookingUpName) return;
    ctx.seq++; ctx.lookingUpName = false;
    clear(ctx.result); clear(ctx.message);
  });
  ctx.name.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); findScanName(ctx); } });
  ctx.message = el("div", { class: "col-sheet-message", role: "status", "aria-live": "polite" });
  ctx.result = el("div", { class: "col-scan-result" });
  ctx.list = el("ul", { class: "col-trade-list col-scan-pending" });
  ctx.checkList = el("ul", { class: "col-trade-list col-scan-checks" });
  ctx.checkTitle = el("h3");
  ctx.checkCurrent = el("p", { class: "sub" });
  ctx.checks = el("section", { class: "col-scan-unsure", tabindex: "-1", hidden: true }, ctx.checkTitle, ctx.checkCurrent, ctx.checkList);
  if (ctx.reads) {
    ctx.captureIntro = el("p", { text: audit ? "Scan each card once. Deck Lab reads the images on the server and discards them."
      : "Scan a loose stack, photograph a page, or take a close-up of one card. Deck Lab reads the images on the server and discards them. Review the batch before adding it." });
    ctx.photoField = el("label", { class: "field col-file-field", for: ctx.input.id },
      el("span", { text: "Take a photo of a card" }), ctx.input);
    ctx.captureHint = el("p", { class: "sub", hidden: true });
    ctx.live = colScanLive(colScanCaptureOptions(ctx, "grid"));
    ctx.grid = colScanGrid(colScanCaptureOptions(ctx, "live"));
    const beforeDismiss = sheet.beforeDismiss;
    sheet.beforeDismiss = () => { ctx.live.stop(); return beforeDismiss(); };
    document.addEventListener("visibilitychange", refreshOnReturn);
  }
  sheet.body.append(
    ...(audit ? [el("p", {text: audit.instructions})] : []),
    audit?.unlisted ? null : ctx.reads ? ctx.captureIntro
      : el("p", { class: "box box-warn col-scan-off", text: COL_SCAN_OFF }),
    ...(ctx.reads ? [ctx.photoField, ctx.live.element, ctx.grid.element, ctx.captureHint] : []),
    ...(!audit ? [colScanDefaults(ctx, id)] : []), ctx.message, ctx.result,
    el("div", { class: "col-scan-typed" },
      el("label", { class: "field", for: ctx.name.id }, el("span", { text: ctx.reads ? "Or type a card's name" : "Type a card's name" }), ctx.name),
      el("button", { type: "button", class: "btn", text: ctx.nameOnly ? "Find card" : "Find its printings", onclick: () => findScanName(ctx) })),
    ctx.checks, el("h3", { text: audit?.unlisted ? "Unlisted printings counted" : audit ? "Counted cards" : "To add" }),
    el("p", {class: "sub", text: audit?.unlisted ? "Check the finish and number of copies for each printing."
      : audit ? "Check the copies you counted before finishing the audit."
      : "This pending batch is not saved when you close. Review and add small batches, or download this batch to import later. Do not import the download after adding the same cards here."}), ctx.list);
  drawScanPending(ctx);
  return ctx;

  function refreshOnReturn() {
    if (!document.hidden && colScanHere(ctx) && !ctx.auditReview) colScanPhotoDisabled(ctx);
  }
}

function colScanSay(ctx, kind, text) {
  clear(ctx.message);
  if (text) ctx.message.append(el("p", { class: `box box-${kind}`, role: kind === "info" ? null : "alert", text }));
}

function colScanHere(ctx, seq) {
  return !ctx.sheet.closed && ctx.current() && (seq === undefined || seq === ctx.seq);
}

function colScanVisible(ctx) {
  return colScanHere(ctx) && !ctx.auditReview && location.hash === ctx.route && !document.hidden && !ctx.sheet.body.hidden
    && ctx.sheet.dialog.isConnected && [...document.querySelectorAll("dialog[open]")].at(-1) === ctx.sheet.dialog;
}

/** Check the original page both before uploading a crop and before showing its answer. */
function colScanCaptureOptions(ctx, other) {
  const isCurrent = () => colScanVisible(ctx);
  const canScan = () => isCurrent() && !ctx.busy && !ctx.picking && !ctx[other]?.active && ctx.unsure.length < COL_SCAN_UNSURE_MAX;
  const onChange = () => {
    if (ctx.captureRead && !ctx.captureRead.current()) ctx.captureRead.controller.abort();
    if (colScanHere(ctx) && !ctx.auditReview) { colScanPhotoDisabled(ctx); drawScanFoot(ctx); }
  };
  return {isCurrent, canScan, onChange, onStart: onChange, addedLabel: () => ctx.last ? colScanLabel(ctx.last) : "",
    submit: (photo, current, sourceLabel) => {
      if (!canScan() || !current()) return Promise.resolve("failed");
      return colScanRead(ctx, () => photo, () => current() && isCurrent(), sourceLabel);
    }};
}

function colScanPhotoDisabled(ctx) {
  const live = ctx.live?.active, grid = ctx.grid?.active;
  ctx.input.disabled = Boolean(ctx.busy || live || grid || ctx.unsure.length >= COL_SCAN_UNSURE_MAX);
  if (!ctx.photoField) return;
  ctx.captureIntro.hidden = Boolean(live || grid);
  ctx.photoField.hidden = Boolean(live || grid);
  ctx.live.element.hidden = Boolean(grid);
  ctx.grid.element.hidden = Boolean(live);
  ctx.live.refresh?.();
  ctx.grid.refresh?.();
}

function colScanControlHere(ctx, node) {
  if (!colScanHere(ctx) || ctx.auditReview || ctx.busy || ctx.picking || !node?.isConnected || !ctx.sheet.dialog.contains(node)
      || [...document.querySelectorAll("dialog[open]")].at(-1) !== ctx.sheet.dialog) return false;
  for (let parent = node; parent && parent !== ctx.sheet.dialog; parent = parent.parentNode) {
    if (parent.hidden || parent.getAttribute?.("aria-hidden") === "true") return false;
    const tag = (parent.tagName || parent.tag || "").toLowerCase();
    if (tag === "details" && !parent.open && parent.getAttribute("open") === null) return false;
  }
  return true;
}

/** Nothing is kept implicitly from a pending row or saved beyond this open sheet. */
function colScanDefaults(ctx, id) {
  const controls = ctx.defaultControls = {};
  const heading = el("summary", {text: "Keep settings for the next cards"});
  const field = (key, label, values) => {
    const input = controls[key] = el("select", {id: id(`keep-${key}`), "aria-label": `${label} for the next cards`},
      values.map(([value, words]) => el("option", {value, text: value ? words : "Don't keep a value"})));
    input.value = "";
    return el("label", {class: "field", for: input.id}, el("span", {text: label}), input);
  };
  const status = ctx.defaultsStatus = el("p", {class: "sub", role: "status", text: "No values kept. Existing cards stay as they are."});
  const keep = el("button", {type: "button", class: "btn", text: "Keep for the next cards", onclick: event => {
    if (!colScanControlHere(ctx, event.currentTarget)) return;
    const values = Object.fromEntries(Object.entries(controls).map(([key, input]) => [key, input.value]));
    if (!COL_CONDITIONS.some(([value]) => value === values.condition)
        || !COL_LANGUAGES.some(([value]) => value === values.language)
        || !["", ...Object.keys(COL_FINISH_WORDS)].includes(values.finish)) return;
    ctx.defaults = values;
    const names = [values.condition, values.language, COL_FINISH_WORDS[values.finish]].filter(Boolean);
    heading.textContent = names.length ? `Kept for the next cards: ${names.join(" · ")}` : "Keep settings for the next cards";
    status.textContent = names.length ? `Kept for cards added next in this sheet: ${names.join(" · ")}. Existing cards stay as they are.`
      : "No values kept. Existing cards stay as they are.";
  }});
  const clearKept = el("button", {type: "button", class: "btn btn-quiet", text: "Clear kept settings", onclick: event => {
    if (!colScanControlHere(ctx, event.currentTarget)) return;
    ctx.defaults = {condition: "", language: "", finish: ""};
    for (const input of Object.values(controls)) input.value = "";
    heading.textContent = "Keep settings for the next cards";
    status.textContent = "No values kept. Existing cards stay as they are.";
  }});
  return el("details", {class: "col-scan-defaults"}, heading,
    el("div", {class: "col-scan-default-fields"},
      field("condition", "Condition", COL_CONDITIONS.map(([value, , words]) => [value, words])),
      field("language", "Language", COL_LANGUAGES),
      field("finish", "Finish", [["", ""], ...Object.entries(COL_FINISH_WORDS)])),
    el("div", {class: "actions"}, keep, clearKept), status,
    el("p", {class: "sub", text: "A language read from a card wins over the kept language. A kept finish applies only when the chosen printing lists it. Reopening this sheet clears the kept settings."}));
}

/** Archive metadata, not photos. Each unresolved scan has one current set of choice controls. */
function drawScanUnsure(ctx) {
  colScanPhotoDisabled(ctx);
  ctx.checks.hidden = !ctx.unsure.length;
  ctx.checkTitle.textContent = `Check these (${ctx.unsure.length})`;
  const next = ctx.audit ? "finishing the audit" : "Review";
  const identity = ctx.nameOnly ? "card" : "printing";
  ctx.checkCurrent.textContent = ctx.currentUnsure ? `The current photo needs a ${identity} choice above. Resolve or skip every photo before ${next}.`
    : `Choose a ${identity}, find it by name or explicitly skip each photo before ${next}.`;
  clear(ctx.checkList);
  for (const entry of ctx.unsure) {
    const current = ctx.currentUnsure === entry;
    const label = entry.source || `Photo ${entry.id}`;
    const reference = entry.source || `photo ${entry.id}`;
    const find = el("button", {type: "button", class: "btn btn-quiet", text: "Find by name…", disabled: ctx.busy,
      "aria-label": `Find ${reference} by name`, onclick: event => {
        if (!colScanControlHere(ctx, event.currentTarget) || !ctx.unsure.includes(entry)) return;
        ctx.seq++; ctx.lookingUpName = false;
        ctx.live?.stop();
        ctx.currentUnsure = ctx.resolving = entry; ctx.last = null; clear(ctx.result);
        ctx.name.value = entry.proposals[0]?.name || "";
        ctx.result.append(el("p", {class: "sub", text: `Type the name for ${reference}, then choose the ${identity}.`}));
        drawScanUnsure(ctx); ctx.name.focus();
      }});
    const skip = el("button", {type: "button", class: "btn btn-quiet", text: "Skip this photo", disabled: ctx.busy,
      "aria-label": `Skip ${reference}`, onclick: event => {
        if (!colScanControlHere(ctx, event.currentTarget) || !ctx.unsure.includes(entry)) return;
        ctx.unsure.splice(ctx.unsure.indexOf(entry), 1);
        if (ctx.audit) ctx.skipped++;
        if (ctx.currentUnsure === entry) { ctx.currentUnsure = null; clear(ctx.result); }
        if (ctx.resolving === entry) ctx.resolving = null;
        drawScanUnsure(ctx); drawScanFoot(ctx);
        colScanSay(ctx, "info", `Skipped ${reference}. ${ctx.audit ? "This photo is excluded from the count." : "No card was added for it."}`);
      }});
    ctx.checkList.append(el("li", {class: "col-scan-check", "data-scan-photo": String(entry.id)},
      el("p", {}, el("strong", {text: label}), ": ", entry.message),
      ...(!current && entry.proposals.length ? [colScanChoices(ctx, entry.proposals, false, entry.proposals, entry)] : []),
      el("div", {class: "actions"}, find, skip)));
  }
}

/** The photo as base64 JPEG bytes, its long side at most COL_SCAN_SIDE (the browser turns it upright as it draws it). */
async function colScanShrink(file) {
  let picture;
  try { picture = await createImageBitmap(file, { imageOrientation: "from-image" }); }
  catch (_) { throw new Error("That photo couldn't be opened. Take it again."); }
  const scale = Math.min(1, COL_SCAN_SIDE / Math.max(picture.width, picture.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(picture.width * scale));
  canvas.height = Math.max(1, Math.round(picture.height * scale));
  canvas.getContext("2d").drawImage(picture, 0, 0, canvas.width, canvas.height);
  if (picture.close) picture.close();
  return colScanEncodeCanvas(canvas);
}

async function colScanEncodeCanvas(canvas) {
  const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", COL_SCAN_QUALITY));
  if (!blob) throw new Error("That photo couldn't be made smaller to send. Take it again.");
  if (blob.size > COL_SCAN_MAX) throw new Error("That photo is still more than 4 MiB once made smaller. Take it again.");
  const url = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("That photo couldn't be read. Take it again."));
    reader.readAsDataURL(blob);
  });
  return url.slice(url.indexOf(",") + 1);
}

/** Send one photo and show what it was read as. */
async function scanPhoto(ctx, file) {
  if (ctx.live?.active || ctx.grid?.active) return;
  return colScanRead(ctx, () => colScanShrink(file), () => ctx.audit ? colScanVisible(ctx) : colScanHere(ctx));
}

/** All capture paths use the existing one-photo recognition route and the same pending batch. */
async function colScanRead(ctx, photoBytes, current, source = "") {
  if (ctx.busy || !ctx.reads || !current()) return "failed";
  if (ctx.unsure.length >= COL_SCAN_UNSURE_MAX) {
    colScanSay(ctx, "warn", `Check these holds ${COL_SCAN_UNSURE_MAX} photos. Resolve or skip some before taking another photo.`); return "failed";
  }
  const seq = ++ctx.seq;
  const read = source || ctx.audit ? {current, controller: new AbortController()} : null;
  ctx.captureRead = read;
  ctx.lookingUpName = false;
  ctx.busy = true;
  ctx.input.disabled = true;
  ctx.currentUnsure = ctx.resolving = ctx.last = null;
  clear(ctx.result);
  drawScanUnsure(ctx); drawScanFoot(ctx);
  clear(ctx.message).append(loadingBox("Reading the card…"));
  try {
    const photo = await photoBytes();
    if (!current() || !colScanHere(ctx, seq)) return "failed";
    const answer = await apiWrite("/api/collection/scan", { space: ctx.space, photo }, "POST",
      read ? {signal: read.controller.signal} : {});
    if (!current() || !colScanHere(ctx, seq)) return "failed";
    if (ctx.audit && answer.space !== ctx.space) throw new Error("The card could not be confirmed for this audit. Scan it again.");
    return drawScanResult(ctx, answer, source);
  } catch (error) {
    if (current() && colScanHere(ctx, seq)) colScanSay(ctx, "crit", error.message);
    return "failed";
  } finally {
    if (ctx.captureRead === read) ctx.captureRead = null;
    if (seq === ctx.seq) {
      ctx.busy = false; ctx.input.disabled = false; ctx.input.value = "";
      if (colScanHere(ctx)) {
        if (!current()) clear(ctx.message);
        drawScanUnsure(ctx); drawScanFoot(ctx);
      }
    }
  }
}

/** "Llanowar Elves (FDN 227 · Foil)". */
function colScanLabel(p) {
  return p.set ? `${p.name} (${colPrinting(p)})` : p.name;
}

/** Retain only printing proposal metadata, never photo bytes or raw OCR lines. */
function colScanProposal(source) {
  const fields = ["name", "canonical_name", "set", "collector_number", "set_name", "finish", "language", "how", "owned"];
  return {...Object.fromEntries(fields.filter(key => Object.hasOwn(source, key)).map(key => [key, source[key]])),
    finishes: Array.isArray(source.finishes) ? [...source.finishes] : null};
}

/** One answer: the one printing read with its name is added (the others offered instead); else the choices to
 * pick from (reprints sharing the number read are all "name and number", so none of them is certain). */
function drawScanResult(ctx, answer, source = "") {
  ctx.lookingUpName = false;
  ctx.currentUnsure = ctx.resolving = null;
  const printings = answer.proposals || [];
  // A deck counts names. Consider every proposed printing before bounding the choices shown.
  const candidates = ctx.nameOnly ? [...new Set(printings.map(p => p.canonical_name || p.name))].map(name => ({name})) : printings;
  const proposals = candidates.slice(0, COL_SCAN_CHOICES).map(colScanProposal);
  let sure = ctx.nameOnly ? candidates.length === 1 && printings.every(p => p.how === "name" || p.how === "name and number")
    && (printings.some(p => p.how === "name and number") || (answer.read?.name_exact && answer.read.name === candidates[0].name))
    : proposals[0]?.how === "name and number" && proposals[1]?.how !== "name and number";
  const message = ctx.nameOnly && proposals.length ? "Check which card this is." : answer.message || "The card couldn't be read.";
  let unsure = sure ? null : {id: ++ctx.nextPhoto, source, message,
    proposals: proposals.map(colScanProposal),
    language: answer.read?.language || proposals.find(p => p.language)?.language || ""};
  if (unsure) {ctx.unsure.push(unsure);ctx.currentUnsure = unsure;ctx.resolving = unsure;}
  clear(ctx.result);
  if (!proposals.length) {
    colScanSay(ctx, "warn", answer.message || "The card couldn't be read.");
    ctx.result.append(el("p", { class: "sub", text: "Type its name below, or take the photo again closer and sharper." }));
    if (!source) ctx.name.focus();
    drawScanUnsure(ctx); drawScanFoot(ctx);
    return "review";
  }
  ctx.last = sure ? addScanCard(ctx, proposals[0], proposals) : null;
  if (sure && !ctx.last) {
    sure = false;
    unsure = {id: ++ctx.nextPhoto, source, message: ctx.audit ? "The count is too large. Check the copies counted."
      : "This printing is at the 999-copy limit. Review a smaller batch; this card is still pending.",
      proposals: proposals.map(colScanProposal), language: proposals[0]?.language || ""};
    ctx.unsure.push(unsure); ctx.currentUnsure = ctx.resolving = unsure;
  }
  colScanSay(ctx, sure ? "info" : "warn", sure ? `${ctx.audit ? "Counted" : "Added"} ${colScanLabel(ctx.last)}.` : unsure?.message || message);
  const others = sure ? proposals.slice(1) : proposals;
  drawScanUnsure(ctx); drawScanFoot(ctx);
  if (ctx.nameOnly && sure) ctx.result.append(colScanCorrectName(ctx, ctx.last, source));
  if (!others.length) return sure ? "added" : "review";
  ctx.result.append(el("p", { class: "sub", text: ctx.nameOnly ? "Choose the card name:" : sure ? "Not that one? Choose the printing instead:" : "Choose its printing:" }),
    colScanChoices(ctx, others, sure, proposals, unsure));
  if (candidates.length > COL_SCAN_CHOICES) {
    const rest = candidates.slice(COL_SCAN_CHOICES).map(colScanProposal);
    ctx.result.append(otherScanPrintings(() => colScanChoices(ctx, rest, sure, proposals, unsure), ctx.nameOnly ? "Other card names…" : undefined));
  }
  return sure ? "added" : "review";
}

/** Put this one physical copy back into Check these, even when others of its name have been counted. */
function colScanCorrectName(ctx, card, source) {
  const seq = ctx.seq;
  return el("button", { type: "button", class: "btn btn-quiet", text: "Correct this scan", onclick: event => {
    if (seq !== ctx.seq || !colScanControlHere(ctx, event.currentTarget) || !ctx.pending.includes(card)) return;
    ctx.live?.stop();
    takeScanCard(ctx, card); ctx.last = null;
    const entry = {id: ++ctx.nextPhoto, source, proposals: [{name: card.name}], message: "Check this card's name."};
    ctx.unsure.push(entry); ctx.currentUnsure = ctx.resolving = entry;
    clear(ctx.result).append(colScanChoices(ctx, entry.proposals, false, entry.proposals, entry));
    drawScanUnsure(ctx); drawScanFoot(ctx);
    ctx.name.value = ""; ctx.name.focus();
    colScanSay(ctx, "info", "Type the name on this card or confirm the original name.");
  } });
}

/** Buttons for printings: each adds its card (replacing the one just added, when instead), with choices (the
 * printings offered, these by default) as its pending row's printing choices. */
function colScanChoices(ctx, printings, instead, choices = printings, unsure = null) {
  const seq = ctx.seq, replaced = ctx.last;
  return el("div", { class: "col-trade-choices", role: "group", "aria-label": ctx.nameOnly ? "Card names" : "Printings" }, printings.map((p) =>
    el("button", { type: "button", class: "btn btn-quiet col-scan-pick", onclick: event => {
      if (!colScanControlHere(ctx, event.currentTarget) || (unsure ? !ctx.unsure.includes(unsure) : seq !== ctx.seq)) return;
      if (instead && replaced) {
        if (ctx.last !== replaced || !ctx.pending.includes(replaced)) return;
      }
      const current = unsure ? ctx.currentUnsure === unsure : true;
      const selected = addScanCard(ctx, p, choices, instead ? replaced : null);
      if (!selected) return;
      if (current) {ctx.last = selected; clear(ctx.result);}
      if (unsure) {
        ctx.unsure.splice(ctx.unsure.indexOf(unsure), 1);
        if (ctx.currentUnsure === unsure) ctx.currentUnsure = null;
        if (ctx.resolving === unsure) ctx.resolving = null;
        drawScanUnsure(ctx); drawScanFoot(ctx);
      }
      colScanSay(ctx, "info", `${ctx.audit ? "Counted" : "Added"} ${colScanLabel(selected)}.`);
    } }, `${colScanLabel(p)}${p.set_name ? ` · ${p.set_name}` : ""}${p.owned ? ` · ${num(p.owned)} listed` : ""}`)));
}

/** Expand the full set only on request, so heavily reprinted cards have a short initial list. */
function otherScanPrintings(draw, label = "Other printings…") {
  const more = el("details", {}, el("summary", {text: label}));
  more.addEventListener("toggle", () => {
    if (more.open && more.children.length === 1) more.append(draw());
  });
  return more;
}

/** A typed name: its printings (an exact name only), to choose from. */
async function findScanName(ctx) {
  const name = ctx.name.value.trim();
  if (ctx.busy || !colScanHere(ctx) || !name || (ctx.audit && !colScanVisible(ctx))) return;
  ctx.live?.stop();
  const seq = ++ctx.seq;
  ctx.nameRequest = seq;
  ctx.lookingUpName = true;
  const unsure = ctx.resolving && ctx.unsure.includes(ctx.resolving) ? ctx.resolving : null;
  ctx.currentUnsure = unsure;
  clear(ctx.result);
  drawScanUnsure(ctx);
  clear(ctx.message).append(loadingBox(`Finding ${name}…`));
  try {
    const answer = await api(`/api/printings?name=${encodeURIComponent(name)}`);
    if (!colScanHere(ctx, seq) || ctx.name.value.trim() !== name) return;
    let printings = (answer.printings || []).filter((p) => (p.finishes || []).length).map((p) => ({ name: answer.name, canonical_name: answer.name,
      set: p.set, set_name: p.set_name, collector_number: p.collector_number, language: unsure?.language || "", finishes: [...p.finishes],
      finish: p.finishes.includes("nonfoil") ? "nonfoil" : p.finishes[0] }));
    if (!printings.length) { colScanSay(ctx, "warn", `${answer.name} has no paper printing to ${ctx.audit ? "count" : "add"}.`); return; }
    if (ctx.audit?.unlisted) {
      const { listed, excluded } = ctx.audit.unlisted;
      if (excluded.has(answer.name)) {
        colScanSay(ctx, "warn", "Loose basic lands are outside this audit.");
        return;
      }
      printings = printings.map(printing => {
        const finishes = printing.finishes.filter(finish => Object.hasOwn(COL_FINISH_WORDS, finish) &&
          !listed.has(colKey({ ...printing, finish })));
        return { ...printing, finishes, finish: finishes[0] };
      }).filter(printing => printing.finishes.length);
      if (!printings.length) {
        colScanSay(ctx, "warn", `Use the listed counts for ${answer.name} in this section.`);
        return;
      }
    }
    colScanSay(ctx, "info", "");
    ctx.last = null;
    if (ctx.nameOnly) {
      ctx.result.append(colScanChoices(ctx, [{name: answer.name}], false, [], unsure));
      ctx.name.value = "";
      return;
    }
    ctx.result.append(el("p", { class: "sub", text: `Choose the printing of ${answer.name}:` }),
      colScanChoices(ctx, printings.slice(0, COL_SCAN_CHOICES), false, printings, unsure));
    if (printings.length > COL_SCAN_CHOICES) {
      ctx.result.append(otherScanPrintings(() => colScanChoices(ctx, printings.slice(COL_SCAN_CHOICES), false, printings, unsure)));
    }
    ctx.name.value = "";
  } catch (error) {
    if (colScanHere(ctx, seq)) colScanSay(ctx, "warn", error.status === 404
      ? `There's no card named "${name}": check the spelling (the exact name, as printed).` : error.message);
  } finally {
    if (ctx.nameRequest === seq) ctx.nameRequest = null;
  }
}

/** Pending cards copied, each with its own printing choices (the import sheet keeps a copy to come back to). */
function colScanCopy(pending) {
  return pending.map((card) => ({ ...card, choices: (card.choices || []).map((c) => ({ ...c })) }));
}

/** Add printings to a pending card's printing choices, each printing once: only its own card's (a scan may
 * propose other cards' printings too), each with the copies listed of its own finish. */
function colScanAddChoices(card, printings) {
  for (const p of printings || []) {
    if (!p || !p.set || (p.name || card.name) !== card.name
      || card.choices.some((c) => c.set === p.set && c.collector_number === p.collector_number)) continue;
    card.choices.push({ name: card.name, ...(p.canonical_name ? {canonical_name: p.canonical_name} : {}),
      set: p.set, collector_number: p.collector_number, set_name: p.set_name || "",
      finish: p.finish || "nonfoil", finishes: Array.isArray(p.finishes) && p.finishes.length ? [...p.finishes] : null,
      owned: p.owned || 0 });
  }
}

/** Another pending card of the same printing, finish, condition and language as card, if any. */
function colScanSame(ctx, card) {
  if (ctx.nameOnly) return ctx.pending.find(c => c !== card && c.name === card.name) || null;
  return ctx.pending.find((c) => c !== card && c.set === card.set && c.collector_number === card.collector_number
    && c.finish === card.finish && c.condition === card.condition && c.language === card.language) || null;
}

/** Put a card on the pending list (one more copy when that printing, finish, condition and language is there),
 * with choices (the printings offered with it) as its printing choices. */
function addScanCard(ctx, p, choices = [p], replaced = null) {
  const kept = ctx.defaults || {};
  const finish = kept.finish && Array.isArray(p.finishes) && p.finishes.includes(kept.finish) ? kept.finish : p.finish || "nonfoil";
  const card = ctx.nameOnly ? { name: p.canonical_name || p.name, quantity: 1 } :
    { name: p.name, ...(ctx.audit ? { canonical_name: p.canonical_name || p.name } : {}), set: p.set, collector_number: p.collector_number, finish,
    quantity: 1, condition: kept.condition || "", language: ctx.audit ? "" : p.language || kept.language || "", choices: [] };
  if (!ctx.nameOnly) colScanAddChoices(card, [p, ...choices]);
  let same = colScanSame(ctx, card);
  if (ctx.audit?.unlisted && !same && ctx.pending.length >= COL_AUDIT_UNLISTED_MAX) {
    colScanSay(ctx, "warn", `Record up to ${num(COL_AUDIT_UNLISTED_MAX)} unlisted printings and finishes per audit.`);
    return null;
  }
  const total = (same?.quantity || 0) + 1 - (same === replaced && replaced ? 1 : 0);
  if (!colScanCount(ctx, total)) return null;
  if (replaced) { takeScanCard(ctx, replaced); same = colScanSame(ctx, card); }
  if (same) {
    same.quantity += 1;
    if (!ctx.nameOnly) colScanAddChoices(same, card.choices);
    drawScanPending(ctx);
    return same;
  }
  ctx.pending.push(card);
  drawScanPending(ctx);
  return card;
}

/** After a change to a pending card, join it to the same one already listed (true, and the list redrawn, when it was). */
function colScanJoin(ctx, card) {
  const same = colScanSame(ctx, card);
  if (!same) return false;
  if (!colScanCount(ctx, same.quantity + card.quantity)) return false;
  same.quantity += card.quantity;
  colScanAddChoices(same, card.choices);
  ctx.pending.splice(ctx.pending.indexOf(card), 1);
  if (ctx.last === card) ctx.last = same;
  drawScanPending(ctx);
  return true;
}

function colScanCount(ctx, quantity) {
  if (ctx.audit) {
    if (Number.isSafeInteger(quantity) && quantity > 0) return true;
    colScanSay(ctx, "warn", "Enter a positive whole number of copies within the supported range.");
    return false;
  }
  if (Number.isInteger(quantity) && quantity >= 1 && quantity <= 999) return true;
  colScanSay(ctx, "warn", "Keep each group between 1 and 999 copies. Nothing was clipped or removed; review a smaller batch.");
  return false;
}

function colScanEdit(ctx, card, changes, choices = []) {
  const candidate = {...card, ...changes};
  const same = ctx.pending.find(c => c !== card && c.set === candidate.set && c.collector_number === candidate.collector_number
    && c.finish === candidate.finish && c.condition === candidate.condition && c.language === candidate.language);
  if (!colScanCount(ctx, (same?.quantity || 0) + candidate.quantity)) { drawScanPending(ctx); return false; }
  Object.assign(card, changes);
  colScanAddChoices(card, choices);
  if (!colScanJoin(ctx, card)) drawScanPending(ctx);
  return true;
}

/** Make a pending card printing p, keeping its finish when p has it (a picked printing's finish is the one
 * picked), then redraw the list. */
function colScanSetPrinting(ctx, card, p, picked = false) {
  const finish = picked || !p.finishes || !p.finishes.includes(card.finish)
    ? p.finish || (p.finishes && p.finishes[0]) || "nonfoil" : card.finish;
  const name = ctx.audit && p.canonical_name ? {canonical_name: p.canonical_name} : {};
  if (!colScanEdit(ctx, card, {...name, set: p.set, collector_number: p.collector_number, finish}, [p])) return false;
  return true;
}

/** "Other printings…": the shared printing picker (GET /api/cards/printings, counting the visitor's own space's
 * copies, which is the space scanned into); the printing and finish picked become the card's. */
async function colScanOther(ctx, card) {
  if (ctx.busy || ctx.picking || !colScanHere(ctx)) return;
  ctx.live?.stop();
  ctx.picking = true;
  let picker, picked;
  try {
    picked = await pickPrinting(card.name, { title: `${card.name}: printing`,
      current: { set: card.set, number: card.collector_number, finish: card.finish },
      onOpen: (sheet) => { picker = sheet; colSheets.add(sheet); } });
  } finally {
    ctx.picking = false;
    if (picker) colSheets.delete(picker);
  }
  // A basic land's "Any printing" isn't a printing to add; a card taken out meanwhile stays out.
  if (!picked || !picked.set || !colScanHere(ctx) || !ctx.pending.includes(card)) return;
  const finish = picked.finish || "nonfoil";
  const finishes = Array.isArray(picked.finish_choices) && picked.finish_choices.length ? picked.finish_choices : null;
  colScanSetPrinting(ctx, card, { name: card.name, set: picked.set, collector_number: picked.number,
    set_name: picked.set_name || "", finish, finishes, owned: picked.owned || 0 }, true);
}

/** "FDN 227 · Foundations · 4 listed": a printing choice's words (its copies listed only when they're of the
 * card's finish now). */
function colScanChoiceWords(c, card) {
  const code = String(c.set).toUpperCase();
  return [`${code} ${c.collector_number}`, c.set_name && c.set_name.toUpperCase() !== code ? c.set_name : null,
    c.owned && c.finish === card.finish ? `${num(c.owned)} listed` : null].filter(Boolean).join(" · ");
}

/** A pending card's printing: a choice of the printings offered for it (the one it is now among them). */
function colScanPrinting(ctx, card) {
  colScanAddChoices(card, [{ name: card.name, set: card.set, collector_number: card.collector_number, finish: card.finish }]);
  const at = String(card.choices.findIndex((c) => c.set === card.set && c.collector_number === card.collector_number));
  const select = el("select", { class: "col-scan-printing", "aria-label": `Printing of ${card.name}`, onchange: () => {
    const c = card.choices[parseInt(select.value, 10)];
    if (!colScanControlHere(ctx, select) || !c) { select.value = at; return; }
    colScanSetPrinting(ctx, card, c);
  } }, card.choices.map((c, i) => el("option", { value: String(i), text: colScanChoiceWords(c, card) })));
  select.value = at;
  return select;
}

function takeScanCard(ctx, card) {
  if (card.quantity > 1) card.quantity -= 1;
  else ctx.pending.splice(ctx.pending.indexOf(card), 1);
  drawScanPending(ctx);
}

const COL_SCAN_PAGE_SIZE = 24;

/** A long batch keeps all its rows for review/export but only renders the editors for one page. */
function colScanPage(ctx) {
  const count = ctx.pending.length, pages = Math.ceil(count / COL_SCAN_PAGE_SIZE);
  if (pages <= 1) { ctx.pendingPage = null; return ctx.pending; }
  const last = pages - 1, page = Math.min(ctx.pendingPage ?? last, last);
  const label = ctx.nameOnly ? "Counted names to show" : "Pending printings to show";
  const picker = el("select", { "aria-label": label, onchange: () => {
    if (!colScanControlHere(ctx, picker)) { picker.value = String(page); return; }
    const selected = Number(picker.value);
    if (!Number.isInteger(selected) || selected < 0 || selected > last) return;
    ctx.pendingPage = selected === last ? null : selected;
    drawScanPending(ctx);
    ctx.list.querySelector(`[aria-label="${label}"]`)?.focus();
  } }, Array.from({ length: pages }, (_, i) => {
    const start = i * COL_SCAN_PAGE_SIZE, end = Math.min(start + COL_SCAN_PAGE_SIZE, count);
    return el("option", { value: String(i), text: `${start + 1}–${end} of ${count}` });
  }));
  picker.value = String(page);
  ctx.list.append(el("li", { class: "col-scan-page" }, el("label", { class: "field" }, ctx.nameOnly ? "Show names" : "Show printings", picker)));
  return ctx.pending.slice(page * COL_SCAN_PAGE_SIZE, (page + 1) * COL_SCAN_PAGE_SIZE);
}

/** The visible printing editors. The footer and import always count the whole batch. */
function drawScanPending(ctx) {
  clear(ctx.list);
  colScanPage(ctx).forEach((card) => {
    const qty = el("input", { type: "number", class: "col-qty-input", inputmode: "numeric", min: 1, max: ctx.audit ? Number.MAX_SAFE_INTEGER : 999, step: 1,
      value: String(card.quantity), "aria-label": `Copies of ${card.name}`,
      onchange: () => {
        if (!colScanControlHere(ctx, qty)) return;
        const count = Number(qty.value);
        if (colScanCount(ctx, count)) card.quantity = count;
        qty.value = String(card.quantity); updateScanCount(ctx);
      } });
    const remove = el("button", { type: "button", class: "btn btn-quiet", text: "Take out", "aria-label": `Take ${card.name} off the list`,
      onclick: event => {
        if (ctx.busy || !colScanHere(ctx) || !ctx.list.contains(event.currentTarget)
            || (ctx.audit && !colScanControlHere(ctx, event.currentTarget))) return;
        ctx.pending.splice(ctx.pending.indexOf(card), 1);
        if (ctx.last === card) ctx.last = null;
        drawScanPending(ctx);
      } });
    if (ctx.nameOnly) {
      ctx.list.append(el("li", { class: "col-trade-line" }, el("span", {class: "col-trade-what", text: card.name}), qty, remove));
      return;
    }
    if (!card.choices) card.choices = [];
    const offered = card.choices.find(c => c.set === card.set && c.collector_number === card.collector_number);
    const knownFinishes = offered?.finishes?.filter(value => Object.hasOwn(COL_FINISH_WORDS, value));
    const auditFinishes = ctx.audit?.mode === "section" && knownFinishes?.length ? knownFinishes : null;
    const finishes = auditFinishes || (ctx.audit?.unlisted ? [card.finish] : Object.keys(COL_FINISH_WORDS));
    const finish = el("select", { "aria-label": `Finish of ${card.name}`,
      onchange: () => {
        if (!colScanControlHere(ctx, finish) || !finishes.includes(finish.value)) { finish.value = card.finish; return; }
        colScanEdit(ctx, card, { finish: finish.value });
      } },
      finishes.map(value => el("option", { value, text: COL_FINISH_WORDS[value] })));
    finish.value = card.finish;
    const condition = el("select", { "aria-label": `Condition of ${card.name}`,
      onchange: () => { if (colScanControlHere(ctx, condition)) colScanEdit(ctx, card, {condition: condition.value}); } },
      COL_CONDITIONS.map(([value, , text]) => el("option", { value, text })));
    condition.value = card.condition;
    // Language: as read off the card, else not recorded (blank, never assumed English).
    const languages = COL_LANGUAGES.some(([v]) => v === card.language) ? COL_LANGUAGES : [...COL_LANGUAGES, [card.language, card.language]];
    const language = el("select", { "aria-label": `Language of ${card.name}`,
      onchange: () => { if (colScanControlHere(ctx, language)) colScanEdit(ctx, card, {language: language.value}); } },
      languages.map(([value, text]) => el("option", { value, text: value ? `${text} (${value})` : text })));
    language.value = card.language;
    ctx.list.append(el("li", { class: "col-trade-line" },
      el("span", { class: "col-trade-what", text: `${card.name} (${String(card.set).toUpperCase()} ${card.collector_number})` }),
      colScanPrinting(ctx, card),
      ctx.audit?.unlisted ? null : el("button", { type: "button", class: "btn btn-quiet", text: "Other printings…", "aria-label": `Other printings of ${card.name}`,
        onclick: event => { if (colScanControlHere(ctx, event.currentTarget)) colScanOther(ctx, card); } }),
      qty, finish, ...(ctx.audit ? [] : [condition, language]), remove));
  });
  if (!ctx.pending.length) ctx.list.append(el("li", { class: "sub", text: "Nothing yet." }));
  drawScanFoot(ctx);
}

/** A quantity edit fires change on blur. Keep the pressed button mounted until its click. */
function updateScanCount(ctx) {
  const cards = ctx.pending.reduce((n, c) => n + c.quantity, 0);
  const capturing = ctx.live?.active || ctx.grid?.active;
  if (ctx.captureHint) {
    ctx.captureHint.hidden = !capturing;
    if (capturing) {
      const finish = ctx.live?.active ? "Stop the camera to review." : "Finish or discard the images to review.";
      ctx.captureHint.textContent = `${cards} pending · ${ctx.unsure.length} to check. ${finish}`;
    }
  }
  const review = ctx.sheet.foot.querySelector('[data-action="review"]');
  if (review) review.textContent = cards ? `Review ${plural(cards, "card")}` : "Review";
  return cards;
}

function drawScanFoot(ctx) {
  if (ctx.auditReview) return;
  const cards = updateScanCount(ctx);
  const capturing = ctx.live?.active || ctx.grid?.active;
  sheetActions(ctx.sheet, [{ text: "Cancel", value: "cancel", onclick: () => ctx.sheet.dismiss() },
    !ctx.audit && !capturing && cards ? {text: "Download pending batch", value: "download", disabled: ctx.busy || ctx.picking || ctx.unsure.length > 0,
      onclick: event => { if (colScanControlHere(ctx, event.currentTarget)) downloadScanBatch(ctx); }} : null,
    !capturing && (ctx.audit || cards || ctx.unsure.length) ? { text: ctx.audit?.unlisted ? "Use these printings"
      : ctx.audit ? "Finish audit" : cards ? `Review ${plural(cards, "card")}` : "Review",
      kind: "primary", value: ctx.audit ? "finish" : "review",
      disabled: ctx.busy || ctx.picking, onclick: event => {
        if (colScanControlHere(ctx, event.currentTarget) && ctx.sheet.foot.contains(event.currentTarget)) reviewScan(ctx);
      } } : null]);
}

/** One CSV field, quoted when it holds a comma, quote or line break. */
function colScanField(value) {
  const text = String(value ?? "");
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

/** The pending list as the collection's own columns (collection_edit's "collection" format). */
function colScanCsv(pending) {
  return [COL_FIELDS.join(","), ...pending.map((c) => COL_FIELDS.map((f) => colScanField(f === "notes" ? "" : c[f])).join(","))]
    .join("\n") + "\n";
}

/** Hand the list to the Import cards sheet's preview: from there it's added as an import is (or taken back). */
function reviewScan(ctx) {
  if (ctx.busy || ctx.picking || ctx.live?.active || ctx.grid?.active || !colScanHere(ctx)
      || (ctx.audit && !colScanVisible(ctx))) return null;
  if (ctx.unsure.length) {
    const next = ctx.audit ? "before finishing the audit." : "before Review. Nothing was sent to the import preview.";
    colScanSay(ctx, "warn", `Resolve or skip ${plural(ctx.unsure.length, "photo")} in Check these ${next}`);
    ctx.checks.focus(); return null;
  }
  if (ctx.audit) {
    if (ctx.nameRequest === ctx.seq) {
      ctx.seq++; ctx.lookingUpName = false;
      clear(ctx.message);
    }
    return ctx.audit.finish(structuredClone(ctx.pending), ctx.skipped, ctx);
  }
  if (!ctx.pending.length) return null;
  const cv = ctx.cv, text = colScanCsv(ctx.pending);
  const d = new Date();
  const day = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  ctx.sheet.close();
  const importing = openImportSheet(cv);
  if (importing) {
    importing.scanned = colScanCopy(ctx.pending);
    importing.scanStartedAt = ctx.scanStartedAt;
    guardScanBatch(importing.sheet, () => colActive(cv) && !importing.sheet.closed,
      () => scanBatchDescription(importing.scanned, "card"), () => importing.busy);
    previewImport(importing, `scan-${day}.csv`, text, ctx.scanStartedAt);
  }
  return importing;
}

/** The import sheet's way back to a scan's pending list, to fix it (null for a file's import). */
function colScanBack(importing) {
  if (!importing.scanned) return null;
  return { text: "Back to the scanned list", value: "back", onclick: () => {
    if (importing.busy || importing.sheet.closed) return;
    importing.sheet.close();
    openScanSheet(importing.cv, importing.scanned, importing.scanStartedAt);
  } };
}

/** Explicit portable checkpoint, using the existing import format; no photos, OCR text or other space's data. */
function downloadScanBatch(ctx) {
  if (ctx.audit || !colScanHere(ctx) || ctx.busy || ctx.picking || ctx.live?.active || ctx.grid?.active || !ctx.pending.length) return;
  if (ctx.unsure.length) {
    colScanSay(ctx, "warn", "Resolve or skip the photos in Check these before downloading. Nothing was downloaded.");
    return;
  }
  let url;
  try {
    url = URL.createObjectURL(new Blob([colScanCsv(ctx.pending)], {type: "text/csv;charset=utf-8"}));
    const link = el("a", {href: url, download: `pending-collection-${new Date().toISOString().slice(0, 10)}.csv`});
    document.body.append(link);
    try { link.click(); } finally { link.remove(); }
    colScanSay(ctx, "info", "Download requested. Check that the CSV is saved before closing. Later, use Import cards in this same collection and review it. Nothing was added now. Don't import it if you add this batch here.");
  } catch (_) {
    colScanSay(ctx, "warn", "The batch couldn't be downloaded. Keep this sheet open and review the cards, or try downloading again.");
  } finally {
    if (url) setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}
