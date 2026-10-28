/* Tokens add/edit and conflict sheets. Loaded after tokens.js, which owns the shared
 * fields, details parser, physical-row helpers and page state. Classic globals remain
 * available to the Tokens page and its other callers. */
"use strict";

// ----------------------------------------------------- the add and edit sheet

/** Add a token card, or edit one ({row}: a GET row). sha256: the list's, as the caller loaded it (left
 * out: it's fetched first, with the face names). faceNames: Scryfall's token face names, for suggestions;
 * keywords: those a details part may list (the GET's), for the "Read as" lines (TOK_KEYWORDS without them).
 * onSaved(answer, words) gets the save's answer; onLatest(latest) the list as it is now, when a
 * conflict's changes are discarded. Returns the sheet. */
function openTokenSheet({ row = null, rows = null, sha256, faceNames, keywords, onSaved, onLatest, onRemove = null, onZoom = null,
  space = HOME_SPACE } = {}) {
  const editing = Boolean(row);
  const sheet = openSheet(editing ? tokLabel(row) : "Add a token card", { wide: true });
  const ctx = { sheet, row, editing, sha256, onSaved, onLatest, busy: false, inputs: {}, space,
    names: faceNames || [], keywords: keywords && keywords.length ? keywords : TOK_KEYWORDS, base: row ? tokBase(row) : null, rows };
  ctx.form = el("form", { class: "tok-form", novalidate: true,
    onsubmit: (event) => { event.preventDefault(); saveTokenFromSheet(ctx); } });
  ctx.message = el("div", { class: "tok-sheet-message", role: "status", "aria-live": "polite" });
  add(ctx.form, [ctx.message, editing ? tokSheetSummary(ctx, row, onZoom) : null, tokFields(ctx, row)]);
  sheet.body.append(ctx.form);
  // Editing: Save, and Remove at the bottom (the sheet's × closes it); adding: Cancel and Save.
  sheetActions(sheet, [
    editing ? null : { text: "Cancel", value: "cancel", onclick: () => sheet.close() },
    { text: "Save", kind: "primary", value: "save", onclick: () => saveTokenFromSheet(ctx) },
    editing && onRemove ? { text: "Remove…", kind: "danger btn-quiet", value: "remove", onclick: () => { sheet.close(); onRemove(); } } : null]);
  if (!editing) ctx.inputs.front.focus();
  return sheet;
}

/** The top of an edit sheet: the card's pictures (with Zoom), and which decks it's used for. */
function tokSheetSummary(ctx, row, onZoom) {
  const { token, example } = tokTileParts(row);
  const pics = [token.img, token.back_img].filter((u) => typeof u === "string" && u.startsWith("/img/"));
  const uses = row.uses || [];
  const leave = () => ctx.sheet.close();
  return el("div", { class: "tok-sheet-top" },
    pics.length ? el("div", { class: "tok-sheet-pics" },
      el("button", { type: "button", class: "tok-sheet-zoom", "aria-label": `Zoom: ${tokLabel(row)}`,
        disabled: onZoom ? null : true, onclick: () => { ctx.sheet.close(); if (onZoom) onZoom(); } },
      pics.map((src) => el("img", { src, alt: "", width: 100, height: 140, loading: "lazy",
        onerror: (event) => { event.currentTarget.hidden = true; } }))),
      example ? el("p", { class: "result-count", text: "Example art: the printing isn't recorded." }) : null) : null,
    el("div", { class: "tok-sheet-uses" },
      (row.shared || []).length ? el("p", { class: "box box-warn tok-shared", text: tokSharedWords(row) }) : null,
      (row.packed || []).length ? el("p", { class: "tok-packed", text: `Packed in ${row.packed.map((h) =>
        `${h.title}${h.quantity > 1 ? ` ×${h.quantity}` : ""}`).join(", ")}` }) : null,
      el("h3", { text: uses.length ? "Used for" : "Not used by a deck" }),
      uses.length ? el("ul", {}, uses.map((use) => {
        const face = use.side === "back" ? row.back : row.front;
        return el("li", {}, `${use.token} in `, el("a", { href: tokHolderHref(use.deck, use.link), text: use.title, onclick: leave }),
          face && row.back ? ` (${face} side)` : null,
          use.state && use.state !== "ready" ? [" ", tokenStateChip(use.state)] : null);
      })) : null));
}

/** "Only 2 cards, used by 3 built decks: A, B and C. They can't all have one packed." or, when a deck packs
 * more than one, "Only 2 cards, but built decks pack 3: A ×2 and B." (the API's "shared"). */
function tokSharedWords(row) {
  const and = (words) => words.length > 1 ? `${words.slice(0, -1).join(", ")} and ${words[words.length - 1]}` : words[0];
  const counts = row.shared.map((h) => h.quantity || 1);
  if (counts.every((n) => n === 1)) {
    return `Only ${plural(row.quantity, "card")}, used by ${plural(row.shared.length, "built deck")}: `
      + `${and(row.shared.map((h) => h.title))}. They can't all have one packed.`;
  }
  return `Only ${plural(row.quantity, "card")}, but built decks pack ${num(counts.reduce((a, b) => a + b, 0))}: `
    + `${and(row.shared.map((h) => `${h.title}${(h.quantity || 1) > 1 ? ` ×${h.quantity}` : ""}`))}.`;
}

function tokFields(ctx, row) {
  const id = (key) => `tok-${key}-${ctx.sheet.heading.id}`;
  const listId = id("names");
  ctx.datalist = el("datalist", { id: listId }, ctx.names.map((name) => el("option", { value: name })));
  const value = (key) => row && row[key] != null ? String(row[key]) : "";
  const text = (key, extra = {}) => el("input", { id: id(key), type: "text", maxlength: TOK_LIMITS[key],
    value: value(key), autocomplete: "off", ...extra });
  const nameInput = (key) => text(key, { list: listId, autocapitalize: "words", spellcheck: "false" });
  const details = (key) => text(key, { placeholder: "e.g. 1/1; green; flying", "aria-describedby": id("details-help") });
  const finish = el("select", { id: id("finish") }, [["", "Not recorded"], ["nonfoil", "Non-foil"], ["foil", "Foil"],
    ["etched", "Etched"]].map(([v, t]) => el("option", { value: v, text: t })));
  finish.value = value("finish");
  const quantity = el("input", { id: id("quantity"), type: "number", inputmode: "numeric", min: 1, max: 9999, step: 1,
    value: row ? String(row.quantity) : "1" });
  ctx.inputs = { front: nameInput("front"), back: nameInput("back"), front_details: details("front_details"),
    back_details: details("back_details"), quantity,
    set: text("set", { autocapitalize: "none", spellcheck: "false", placeholder: "e.g. tltr" }),
    front_collector_number: text("front_collector_number", { autocapitalize: "none", spellcheck: "false" }),
    back_collector_number: text("back_collector_number", { autocapitalize: "none", spellcheck: "false" }),
    finish, notes: el("textarea", { id: id("notes"), rows: 3, maxlength: TOK_LIMITS.notes, autocomplete: "off" }) };
  ctx.inputs.notes.value = value("notes");
  ctx.reading = {};
  for (const key of ["front_details", "back_details"]) {
    const input = ctx.inputs[key];
    ctx.reading[key] = tokReadingLine((text) => { input.value = text; tokRefreshReading(ctx); input.focus(); }, ctx.keywords, () => ctx.names);
    input.addEventListener("input", () => ctx.reading[key].refresh(input.value));
  }
  ctx.suggest = {};
  for (const key of ["front", "back"]) {
    ctx.suggest[key] = el("div", { class: "tok-suggest", "aria-live": "polite" });
    ctx.inputs[key].addEventListener("blur", () => tokOfferName(ctx, key));
  }
  const single = el("input", { id: id("single"), type: "checkbox", class: "tok-single-box",
    onchange: () => tokSingleChanged(ctx) });
  single.checked = Boolean(row && (row.single_sided || (!row.back && new RegExp(TOK_SINGLE, "i").test(row.notes || ""))));
  ctx.inputs.single = single;
  const field = (key, label, input, ...after) => el("label", { class: `field tok-field-${key}`, for: input.id },
    el("span", { text: label }), input, ...after);
  const printing = el("details", { class: "tok-printing-fields", open: Boolean(row && (row.set || row.finish ||
    row.front_collector_number || row.back_collector_number)) },
    el("summary", { text: "Printing (optional)" }),
    el("div", { class: "tok-fields" },
      field("set", "Set code", ctx.inputs.set),
      field("finish", "Finish", finish),
      field("front_collector_number", "Front collector number", ctx.inputs.front_collector_number),
      field("back_collector_number", "Back collector number", ctx.inputs.back_collector_number)));
  const grid = el("div", { class: "tok-fields" },
    el("div", { class: "field tok-field-front" }, el("label", { for: ctx.inputs.front.id, text: "Front: token name" }),
      ctx.inputs.front, ctx.suggest.front),
    el("div", { class: "field tok-field-back" }, el("label", { for: ctx.inputs.back.id, text: "Back: token name" }),
      ctx.inputs.back, ctx.suggest.back),
    el("div", { class: "tok-sides" },
      el("button", { type: "button", class: "btn tok-sheet-mutate", text: "Swap front and back",
        onclick: () => tokSwap(ctx) }),
      el("label", { class: "tok-check", for: single.id }, single, el("span", { text: "Single-sided (checked)" }))),
    el("div", { class: "tok-details" }, field("front_details", "Front details", ctx.inputs.front_details),
      ctx.reading.front_details),
    el("div", { class: "tok-details" }, field("back_details", "Back details", ctx.inputs.back_details),
      ctx.reading.back_details),
    el("p", { id: id("details-help"), class: "field-hint tok-help",
      text: "The names are just the token's name (Angel, not White Angel 4/4 flying); its power/toughness, colour and "
        + "abilities go here, separated by ';'. Leave blank if you haven't checked. Write 'no deathtouch' to rule something out; 'colour unconfirmed' for unknowns." }),
    field("quantity", "Quantity", quantity),
    field("notes", "Notes", ctx.inputs.notes));
  tokSingleChanged(ctx, true);
  tokRefreshReading(ctx);
  return el("div", { class: "tok-sheet-fields" }, ctx.datalist, grid, printing);
}

/** "Did you mean Spirit?" under a name typed in a slightly different way, with a one-tap fix. */
function tokOfferName(ctx, key) {
  const box = ctx.suggest[key];
  clear(box);
  const input = ctx.inputs[key];
  const split = tokSplitDescription(input.value, ctx.names);
  if (split) {
    const details = ctx.inputs[`${key}_details`];
    box.append(el("button", { type: "button", class: "btn btn-quiet tok-sheet-mutate",
      text: `Use ${split.name}, with "${split.details}" in ${key === "back" ? "Back" : "Front"} details`,
      onclick: () => { input.value = split.name; details.value = split.details;
        clear(box); tokRefreshReading(ctx); input.focus(); } }));
    return;
  }
  const better = tokSuggest(input.value, ctx.names);
  if (!better) return;
  box.append(el("button", { type: "button", class: "btn btn-quiet tok-sheet-mutate", text: `Did you mean ${better}?`,
    onclick: () => { input.value = better; clear(box); input.focus(); } }));
}

function tokSwap(ctx) {
  const i = ctx.inputs;
  for (const [a, b] of [["front", "back"], ["front_details", "back_details"],
    ["front_collector_number", "back_collector_number"]]) {
    [i[a].value, i[b].value] = [i[b].value, i[a].value];
  }
  for (const key of ["front", "back"]) clear(ctx.suggest[key]);
  if (i.single.checked && i.back.value) { i.single.checked = false; tokSingleChanged(ctx); }
  tokRefreshReading(ctx);
}

/** Redraws the "Read as" lines under both details fields (after a change the page made, not a keystroke). */
function tokRefreshReading(ctx) {
  for (const [key, line] of Object.entries(ctx.reading || {})) line.refresh(ctx.inputs[key].value);
}

/** Notes without "single-sided verified" (and the "; " that joined it): "printing unconfirmed". */
function tokDropSingle(notes) {
  return String(notes || "").replace(new RegExp(TOK_SINGLE, "gi"), "")
    .replace(/\s*;\s*(?:;\s*)+/g, "; ").replace(/^\s*;\s*|\s*;\s*$/g, "").replace(/\s{2,}/g, " ").trim();
}

/** The single-sided box: ticked, the back is cleared and the notes say "single-sided verified"; unticked,
 * the back can be typed again and those words come off the notes, whoever wrote them (a back with them
 * fails tokens --check). first: drawing the sheet, when the notes are left as they are. */
function tokSingleChanged(ctx, first = false) {
  const i = ctx.inputs;
  const single = Boolean(i.single.checked);
  if (single) {
    i.back.value = ""; i.back_details.value = ""; i.back_collector_number.value = "";
    clear(ctx.suggest.back);
    if (!new RegExp(TOK_SINGLE, "i").test(i.notes.value)) {
      i.notes.value = [i.notes.value.trim(), TOK_SINGLE].filter(Boolean).join("; ");
    }
  } else if (!first && new RegExp(TOK_SINGLE, "i").test(i.notes.value)) {
    i.notes.value = tokDropSingle(i.notes.value);
  }
  for (const key of ["back", "back_details", "back_collector_number"]) i[key].disabled = single;
  if (!first) tokRefreshReading(ctx);
}

function tokSheetBusy(ctx, busy) {
  ctx.busy = busy;
  ctx.form.setAttribute("aria-busy", String(busy));
  for (const control of ctx.form.querySelectorAll(".tok-sheet-mutate")) control.disabled = busy;
  for (const button of ctx.sheet.foot.querySelectorAll("button")) button.disabled = busy;
}

function tokProblem(ctx, key, words) {
  clear(ctx.message).append(el("div", { class: "box box-warn", role: "alert" }, el("p", { text: words })));
  if (key && ctx.inputs[key]) ctx.inputs[key].focus();
  return null;
}

/** The form as a save's row, or null (with the problem said) when it can't be saved. */
function tokFormRow(ctx) {
  const value = (key) => String(ctx.inputs[key].value || "").replace(/\s+/g, " ").trim();
  const row = Object.fromEntries(TOK_FIELDS.map((key) => [key, key === "quantity" ? "" : value(key)]));
  row.set = row.set.toLowerCase();
  for (const key of ["front_collector_number", "back_collector_number"]) row[key] = row[key].replace(/\s+/g, "");
  const quantityText = value("quantity");
  const quantity = Number(quantityText);
  if (!row.front) return tokProblem(ctx, "front", "Give the front face's name, like “Zombie” or “The Monarch”.");
  if (quantityText === "" || !Number.isInteger(quantity) || quantity < 1 || quantity > 9999) {
    return tokProblem(ctx, "quantity", "The quantity is the number of physical cards: a whole number from 1 to 9999.");
  }
  if (row.set && !/^[a-z0-9]{2,8}$/.test(row.set)) {
    return tokProblem(ctx, "set", "The set code is 2 to 8 letters or digits, like “tltr” (or leave it blank).");
  }
  row.quantity = quantity;
  return row;
}

async function saveTokenFromSheet(ctx) {
  if (ctx.busy || ctx.sheet.closed) return;
  const row = tokFormRow(ctx);
  if (!row) return;
  const body = { action: ctx.editing ? "edit" : "add", row };
  if (ctx.editing) body.base = ctx.base;
  tokSheetBusy(ctx, true);
  try {
    if (ctx.sha256 === undefined) {
      const data = await api(tokPath(ctx.space));
      ctx.sha256 = data.sha256;
      if (!ctx.names.length && data.face_names) ctx.names = data.face_names;
    }
    await tokSend(ctx, { ...body, sha256: ctx.sha256 });
  } catch (error) {
    if (!ctx.sheet.closed) clear(ctx.message).append(el("div", { class: "box box-crit", role: "alert" }, el("p", { text: error.message })));
  } finally {
    if (!ctx.sheet.closed) tokSheetBusy(ctx, false);
  }
}

/** Send a save; on success close the sheet and hand on the answer. A card that's already listed asks
 * what to do; a list changed meanwhile offers to re-apply. */
async function tokSend(ctx, body) {
  clear(ctx.message).append(loadingBox("Saving…"));
  try {
    const answer = await apiWrite("/api/tokens/save", tokBody(ctx, body));
    const label = tokLabel(body.row || body.base);
    const words = `${label} ${body.action === "add" ? "added" : "saved"}.`;
    state.library = null;
    ctx.sheet.close();
    if (!ctx.onSaved) toast(words);
    else ctx.onSaved(answer, words);
  } catch (error) {
    if (ctx.sheet.closed) return;
    if (error.status === 409 && error.data && error.data.same_row) { showTokenSameRow(ctx, error, body); return; }
    if (error.status === 409 && error.data && error.data.latest) { showTokenConflict(ctx, error, body); return; }
    clear(ctx.message).append(el("div", { class: "box box-crit", role: "alert" }, el("p", { text: error.message })));
  }
}

/** The card is already listed: add to that card's quantity, or (when either card isn't fully known, so
 * they may differ) keep this one apart. The page never merges rows by itself. */
function showTokenSameRow(ctx, error, body) {
  const same = error.data.same_row;
  const other = tokBase(same.row || {});
  const allowed = typeof same.separate_allowed === "boolean" ? same.separate_allowed
    : !tokKnown(other) || !tokKnown(tokBase(body.row));
  const n = Number(body.row.quantity);
  const buttons = [];
  if (body.action === "add") {
    buttons.push(el("button", { type: "button", class: "btn btn-primary tok-sheet-mutate", text: `Add ${n} to that card`,
      onclick: () => tokSend(ctx, { action: "edit", sha256: body.sha256, base: other,
        row: { ...other, quantity: Number(other.quantity) + n } }) }));
  }
  if (allowed) {
    buttons.push(el("button", { type: "button", class: "btn tok-sheet-mutate", text: "Keep it as a separate card",
      onclick: () => tokSend(ctx, { ...body, separate: true }) }));
  }
  clear(ctx.message).append(el("div", { class: "box box-warn", role: "alert" },
    el("p", { text: error.message }),
    !allowed && body.action !== "add"
      ? el("p", { text: "Change that card's quantity instead, then remove this one." }) : null,
    buttons.length ? el("div", { class: "actions" }, buttons) : null));
}

function showTokenConflict(ctx, error, body) {
  const latest = error.data.latest;
  const conflict = error.data.conflict || {};
  const sheet = ctx.sheet;
  sheet.heading.textContent = tokConflictTitle(conflict);
  clear(sheet.body).append(ctx.message);
  clear(ctx.message);
  const discard = { text: "Discard my changes", kind: "discard", value: "discard",
    onclick: () => { sheet.close(); if (ctx.onLatest) ctx.onLatest(latest); } };
  const resend = (next) => {
    ctx.sha256 = latest.sha256;
    ctx.rows = latest.rows || null;     // a further conflict is judged against this list
    if (latest.face_names && latest.face_names.length) ctx.names = latest.face_names;
    clear(sheet.body).append(ctx.message);
    sheetActions(sheet, [{ text: "Saving…", kind: "primary", value: "saving", disabled: true }]);
    return tokSend(ctx, { ...next, sha256: latest.sha256 }).then(() => {
      // Another error (not a conflict, which draws this again): its message shows; let the sheet be left.
      if (!sheet.closed && sheet.foot.querySelector('[data-action="saving"]')) {
        sheetActions(sheet, [{ text: "Close", onclick: () => sheet.close() }, discard]);
      }
    });
  };
  sheet.body.append(el("div", { class: "box box-warn" }, el("p", { text: error.message })),
    el("p", { text: "Nothing was saved. Your changes are still here." }));
  if (body.action === "add") {
    sheet.body.append(el("p", { text: "Load the latest list and your new token card is added to it." }));
    sheetActions(sheet, [{ text: "Load the latest and re-apply my changes", kind: "primary", onclick: () => resend(body) }, discard]);
    return;
  }
  const where = tokLocate(latest.rows, body.base, conflict, ctx.rows);
  if (where.state === "gone") {
    // Removed: adding is offered only as an explicit add of these values, never as a quiet re-save.
    const quantity = Number(body.row.quantity);
    sheet.body.append(el("p", { text: "It has been removed from the list since you opened it, so there's nothing left to edit." }),
      el("p", { text: `If you still have it, add it as a new card with your values (${tokLabel(body.row)} ×${quantity}). Otherwise discard your changes.` }));
    sheetActions(sheet, [{ text: `Add ${tokLabel(body.row)} ×${quantity} as a new card`, kind: "primary", onclick: () => {
      ctx.editing = false;
      const { base, ...rest } = body;
      resend({ ...rest, action: "add" });
    } }, discard]);
    return;
  }
  if (where.state === "unsure") {
    sheet.body.append(el("p", { text: "It was changed since you opened it, and which card in the list it is now can't be told for sure, so your changes can't be put back on top. Discard them, then edit the right card in the list as it is now." }));
    sheetActions(sheet, [{ ...discard, kind: "primary" }]);
    return;
  }
  const theirs = where.row;
  if (where.state === "changed") {
    sheet.body.append(el("p", { text: `This card was changed meanwhile: ${tokChangedWords(body.base, tokBase(theirs))}.` }));
  }
  // My changes go on top of the row as it is now, field by field; where we both changed a field, I choose.
  const { row, clashes } = rebaseFields(tokBase(body.row), body.base, tokBase(theirs), TOK_FIELDS);
  const next = () => ({ ...body, row: { ...row, quantity: Number(row.quantity) }, base: tokBase(theirs) });
  ctx.base = tokBase(theirs);
  if (!clashes.length) {
    sheet.body.append(el("p", { text: "Load the latest and your changes are put back on top of it, field by field." }));
    sheetActions(sheet, [{ text: "Load the latest and re-apply my changes", kind: "primary", onclick: () => resend(next()) }, discard]);
    return;
  }
  sheet.body.append(el("p", { text: "You both changed these. Choose which to keep:" }));
  clashes.forEach((clash, n) => {
    const name = `tok-clash-${sheet.heading.id}-${n}`;
    const option = (which, value, checked) => el("label", { class: "tok-choice" },
      el("input", { type: "radio", name, value: which, checked, onchange: () => { row[clash.key] = value; } }),
      el("span", { text: `${which === "mine" ? "Yours" : "Theirs"}: ${value === "" ? "(blank)" : value}` }));
    sheet.body.append(el("fieldset", { class: "tok-clash" }, el("legend", { text: TOK_FIELD_WORDS[clash.key] }),
      option("mine", clash.mine, true), option("theirs", clash.theirs, false)));
  });
  sheetActions(sheet, [{ text: "Save with these choices", kind: "primary", onclick: () => resend(next()) }, discard]);
}
