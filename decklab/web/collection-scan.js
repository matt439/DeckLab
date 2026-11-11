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
const COL_SCAN_CHOICES = 8;             // printings offered at most for one card
const COL_SCAN_UNSURE_MAX = 50;         // bounded proposal metadata only; never photo bytes
const COL_SCAN_OFF = "Photos can't be read on this server, so type each card's name instead.";

/** Whether the server can read photos: false only when a view says so (an older server's says nothing). */
function scanAvailable(data) {
  return !(data && data.scan && data.scan.available === false);
}

/** Open the sheet (where the visitor may change this collection), with the pending cards brought back from
 * the import sheet, if any. Returns its context, or null. */
function openScanSheet(cv, pending = []) {
  if (!colActive(cv) || cv.busy || !cv.editable) return null;
  const sheet = colOpenSheet(`Scan cards into ${colWhose(cv.space)}`, { wide: true });
  const id = (key) => `col-scan-${key}-${sheet.heading.id}`;
  const ctx = { cv, sheet, pending: colScanCopy(pending), busy: false, picking: false, seq: 0, last: null,
    reads: scanAvailable(cv.data), defaults: {condition: "", language: "", finish: ""},
    unsure: [], nextPhoto: 0, currentUnsure: null, resolving: null, space: cv.space, profile: cv.profile };
  ctx.input = el("input", { id: id("photo"), type: "file", accept: "image/*", capture: "environment", class: "col-file" });
  ctx.input.addEventListener("change", () => {
    const file = ctx.input.files && ctx.input.files[0];
    if (file) scanPhoto(ctx, file);
  });
  ctx.name = el("input", { id: id("name"), type: "text", autocomplete: "off", spellcheck: "false",
    placeholder: "The card's exact name" });
  ctx.name.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); findScanName(ctx); } });
  ctx.message = el("div", { class: "col-sheet-message", role: "status", "aria-live": "polite" });
  ctx.result = el("div", { class: "col-scan-result" });
  ctx.list = el("ul", { class: "col-trade-list col-scan-pending" });
  ctx.checkList = el("ul", { class: "col-trade-list col-scan-checks" });
  ctx.checkTitle = el("h3");
  ctx.checkCurrent = el("p", { class: "sub" });
  ctx.checks = el("section", { class: "col-scan-unsure", tabindex: "-1", hidden: true }, ctx.checkTitle, ctx.checkCurrent, ctx.checkList);
  sheet.body.append(
    ctx.reads ? el("p", { text: "Photograph one card at a time, filling the frame with it. Each photo is read on the PC and "
      + "never kept. Nothing is added until you review the list." })
      : el("p", { class: "box box-warn col-scan-off", text: COL_SCAN_OFF }),
    // The photo field only where photos can be read (an empty div keeps append free of null).
    ctx.reads ? el("label", { class: "field col-file-field", for: ctx.input.id },
      el("span", { text: "Take a photo of a card" }), ctx.input) : el("div", { hidden: true }),
    colScanDefaults(ctx, id), ctx.message, ctx.result,
    el("div", { class: "col-scan-typed" },
      el("label", { class: "field", for: ctx.name.id }, el("span", { text: ctx.reads ? "Or type a card's name" : "Type a card's name" }), ctx.name),
      el("button", { type: "button", class: "btn", text: "Find its printings", onclick: () => findScanName(ctx) })),
    ctx.checks, el("h3", { text: "To add" }), ctx.list);
  drawScanPending(ctx);
  return ctx;
}

function colScanSay(ctx, kind, text) {
  clear(ctx.message);
  if (text) ctx.message.append(el("p", { class: `box box-${kind}`, role: kind === "info" ? null : "alert", text }));
}

function colScanHere(ctx, seq) {
  return !ctx.sheet.closed && colActive(ctx.cv) && ctx.cv.space === ctx.space && ctx.cv.profile === ctx.profile
    && (seq === undefined || seq === ctx.seq);
}

function colScanControlHere(ctx, node) {
  if (!colScanHere(ctx) || !ctx.cv.editable || ctx.busy || ctx.picking || !node?.isConnected || !ctx.sheet.dialog.contains(node)
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
  ctx.input.disabled = ctx.busy || ctx.unsure.length >= COL_SCAN_UNSURE_MAX;
  ctx.checks.hidden = !ctx.unsure.length;
  ctx.checkTitle.textContent = `Check these (${ctx.unsure.length})`;
  ctx.checkCurrent.textContent = ctx.currentUnsure ? "The current photo needs a printing choice above. Resolve or skip every photo before Review."
    : "Choose a printing, find it by name or explicitly skip each photo before Review.";
  clear(ctx.checkList);
  for (const entry of ctx.unsure) {
    const current = ctx.currentUnsure === entry;
    const find = el("button", {type: "button", class: "btn btn-quiet", text: "Find by name…", disabled: ctx.busy,
      "aria-label": `Find photo ${entry.id} by name`, onclick: event => {
        if (!colScanControlHere(ctx, event.currentTarget) || !ctx.unsure.includes(entry)) return;
        ctx.currentUnsure = ctx.resolving = entry; ctx.last = null; clear(ctx.result);
        ctx.name.value = entry.proposals[0]?.name || "";
        ctx.result.append(el("p", {class: "sub", text: `Type the name for photo ${entry.id}, then choose its printing.`}));
        drawScanUnsure(ctx); ctx.name.focus();
      }});
    const skip = el("button", {type: "button", class: "btn btn-quiet", text: "Skip this photo", disabled: ctx.busy,
      "aria-label": `Skip photo ${entry.id}`, onclick: event => {
        if (!colScanControlHere(ctx, event.currentTarget) || !ctx.unsure.includes(entry)) return;
        ctx.unsure.splice(ctx.unsure.indexOf(entry), 1);
        if (ctx.currentUnsure === entry) { ctx.currentUnsure = null; clear(ctx.result); }
        if (ctx.resolving === entry) ctx.resolving = null;
        drawScanUnsure(ctx); drawScanFoot(ctx);
        colScanSay(ctx, "info", `Skipped photo ${entry.id}. No card was added for it.`);
      }});
    ctx.checkList.append(el("li", {class: "col-scan-check", "data-scan-photo": String(entry.id)},
      el("p", {}, el("strong", {text: `Photo ${entry.id}`}), ": ", entry.message),
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
  if (ctx.busy || !ctx.reads || !colScanHere(ctx)) return;
  if (ctx.unsure.length >= COL_SCAN_UNSURE_MAX) {
    colScanSay(ctx, "warn", `Check these holds ${COL_SCAN_UNSURE_MAX} photos. Resolve or skip some before taking another photo.`); return;
  }
  const seq = ++ctx.seq;
  ctx.busy = true;
  ctx.input.disabled = true;
  ctx.currentUnsure = ctx.resolving = ctx.last = null;
  clear(ctx.result);
  drawScanUnsure(ctx); drawScanFoot(ctx);
  clear(ctx.message).append(loadingBox("Reading the card…"));
  try {
    const photo = await colScanShrink(file);
    if (!colScanHere(ctx, seq)) return;
    const answer = await apiWrite("/api/collection/scan", { space: ctx.cv.space, photo });
    if (!colScanHere(ctx, seq)) return;
    drawScanResult(ctx, answer);
  } catch (error) {
    if (colScanHere(ctx, seq)) colScanSay(ctx, "crit", error.message);
  } finally {
    if (seq === ctx.seq) {
      ctx.busy = false; ctx.input.disabled = false; ctx.input.value = "";
      if (colScanHere(ctx)) { drawScanUnsure(ctx); drawScanFoot(ctx); }
    }
  }
}

/** "Llanowar Elves (FDN 227 · Foil)". */
function colScanLabel(p) {
  return `${p.name} (${colPrinting(p)})`;
}

/** Retain only printing proposal metadata, never photo bytes or raw OCR lines. */
function colScanProposal(source) {
  const fields = ["name", "set", "collector_number", "set_name", "finish", "language", "how", "owned"];
  return {...Object.fromEntries(fields.filter(key => Object.hasOwn(source, key)).map(key => [key, source[key]])),
    finishes: Array.isArray(source.finishes) ? [...source.finishes] : null};
}

/** One answer: the one printing read with its name is added (the others offered instead); else the choices to
 * pick from (reprints sharing the number read are all "name and number", so none of them is certain). */
function drawScanResult(ctx, answer) {
  ctx.currentUnsure = ctx.resolving = null;
  const proposals = (answer.proposals || []).slice(0, COL_SCAN_CHOICES).map(colScanProposal);
  const sure = proposals[0]?.how === "name and number" && proposals[1]?.how !== "name and number";
  const unsure = sure ? null : {id: ++ctx.nextPhoto, message: answer.message || "The card couldn't be read.",
    proposals: proposals.map(colScanProposal),
    language: answer.read?.language || proposals.find(p => p.language)?.language || ""};
  if (unsure) {ctx.unsure.push(unsure);ctx.currentUnsure = unsure;ctx.resolving = unsure;}
  clear(ctx.result);
  if (!proposals.length) {
    colScanSay(ctx, "warn", answer.message || "The card couldn't be read.");
    ctx.result.append(el("p", { class: "sub", text: "Type its name below, or take the photo again closer and sharper." }));
    ctx.name.focus();
    drawScanUnsure(ctx); drawScanFoot(ctx);
    return;
  }
  ctx.last = sure ? addScanCard(ctx, proposals[0], proposals) : null;
  colScanSay(ctx, sure ? "info" : "warn", sure ? `Added ${colScanLabel(ctx.last)}.` : answer.message);
  const others = sure ? proposals.slice(1) : proposals;
  drawScanUnsure(ctx); drawScanFoot(ctx);
  if (!others.length) return;
  ctx.result.append(el("p", { class: "sub", text: sure ? "Not that one? Choose the printing instead:" : "Choose its printing:" }),
    colScanChoices(ctx, others, sure, proposals, unsure));
}

/** Buttons for printings: each adds its card (replacing the one just added, when instead), with choices (the
 * printings offered, these by default) as its pending row's printing choices. */
function colScanChoices(ctx, printings, instead, choices = printings, unsure = null) {
  const seq = ctx.seq, replaced = ctx.last;
  return el("div", { class: "col-trade-choices", role: "group", "aria-label": "Printings" }, printings.map((p) =>
    el("button", { type: "button", class: "btn btn-quiet col-scan-pick", onclick: event => {
      if (!colScanControlHere(ctx, event.currentTarget) || (unsure ? !ctx.unsure.includes(unsure) : seq !== ctx.seq)) return;
      if (instead && replaced) {
        if (ctx.last !== replaced || !ctx.pending.includes(replaced)) return;
        takeScanCard(ctx, replaced);
      }
      const current = unsure ? ctx.currentUnsure === unsure : true;
      const selected = addScanCard(ctx, p, choices);
      if (current) {ctx.last = selected; clear(ctx.result);}
      if (unsure) {
        ctx.unsure.splice(ctx.unsure.indexOf(unsure), 1);
        if (ctx.currentUnsure === unsure) ctx.currentUnsure = null;
        if (ctx.resolving === unsure) ctx.resolving = null;
        drawScanUnsure(ctx); drawScanFoot(ctx);
      }
      colScanSay(ctx, "info", `Added ${colScanLabel(selected)}.`);
    } }, `${colScanLabel(p)}${p.set_name ? ` · ${p.set_name}` : ""}${p.owned ? ` · ${num(p.owned)} listed` : ""}`)));
}

/** A typed name: its printings (an exact name only), to choose from. */
async function findScanName(ctx) {
  const name = ctx.name.value.trim();
  if (ctx.busy || !colScanHere(ctx) || !name) return;
  const seq = ++ctx.seq;
  const unsure = ctx.resolving && ctx.unsure.includes(ctx.resolving) ? ctx.resolving : null;
  ctx.currentUnsure = unsure;
  clear(ctx.result);
  drawScanUnsure(ctx);
  clear(ctx.message).append(loadingBox(`Finding ${name}…`));
  try {
    const answer = await api(`/api/printings?name=${encodeURIComponent(name)}`);
    if (!colScanHere(ctx, seq)) return;
    const printings = (answer.printings || []).filter((p) => (p.finishes || []).length).map((p) => ({ name: answer.name,
      set: p.set, set_name: p.set_name, collector_number: p.collector_number, language: unsure?.language || "", finishes: [...p.finishes],
      finish: p.finishes.includes("nonfoil") ? "nonfoil" : p.finishes[0] }));
    if (!printings.length) { colScanSay(ctx, "warn", `${answer.name} has no paper printing to add.`); return; }
    colScanSay(ctx, "info", "");
    ctx.last = null;
    ctx.result.append(el("p", { class: "sub", text: `Choose the printing of ${answer.name}:` }),
      colScanChoices(ctx, printings.slice(0, COL_SCAN_CHOICES), false, printings, unsure));
    ctx.name.value = "";
  } catch (error) {
    if (colScanHere(ctx, seq)) colScanSay(ctx, "warn", error.status === 404
      ? `There's no card named "${name}": check the spelling (the exact name, as printed).` : error.message);
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
    card.choices.push({ name: card.name, set: p.set, collector_number: p.collector_number, set_name: p.set_name || "",
      finish: p.finish || "nonfoil", finishes: Array.isArray(p.finishes) && p.finishes.length ? [...p.finishes] : null,
      owned: p.owned || 0 });
  }
}

/** Another pending card of the same printing, finish, condition and language as card, if any. */
function colScanSame(ctx, card) {
  return ctx.pending.find((c) => c !== card && c.set === card.set && c.collector_number === card.collector_number
    && c.finish === card.finish && c.condition === card.condition && c.language === card.language) || null;
}

/** Put a card on the pending list (one more copy when that printing, finish, condition and language is there),
 * with choices (the printings offered with it) as its printing choices. */
function addScanCard(ctx, p, choices = [p]) {
  const kept = ctx.defaults || {};
  const finish = kept.finish && Array.isArray(p.finishes) && p.finishes.includes(kept.finish) ? kept.finish : p.finish || "nonfoil";
  const card = { name: p.name, set: p.set, collector_number: p.collector_number, finish,
    quantity: 1, condition: kept.condition || "", language: p.language || kept.language || "", choices: [] };
  colScanAddChoices(card, [p, ...choices]);
  const same = colScanSame(ctx, card);
  if (same) {
    same.quantity = Math.min(999, same.quantity + 1);
    colScanAddChoices(same, card.choices);
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
  same.quantity = Math.min(999, same.quantity + card.quantity);
  colScanAddChoices(same, card.choices);
  ctx.pending.splice(ctx.pending.indexOf(card), 1);
  if (ctx.last === card) ctx.last = same;
  drawScanPending(ctx);
  return true;
}

/** Make a pending card printing p, keeping its finish when p has it (a picked printing's finish is the one
 * picked), then redraw the list. */
function colScanSetPrinting(ctx, card, p, picked = false) {
  card.set = p.set;
  card.collector_number = p.collector_number;
  if (picked || !p.finishes || !p.finishes.includes(card.finish)) card.finish = p.finish || (p.finishes && p.finishes[0]) || "nonfoil";
  colScanAddChoices(card, [p]);
  if (!colScanJoin(ctx, card)) drawScanPending(ctx);
}

/** "Other printings…": the shared printing picker (GET /api/cards/printings, counting the visitor's own space's
 * copies, which is the space scanned into); the printing and finish picked become the card's. */
async function colScanOther(ctx, card) {
  if (ctx.busy || ctx.picking || !colScanHere(ctx)) return;
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
    if (ctx.busy || !c) { select.value = at; return; }
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

/** The pending list, each card with its printing, copies, finish, condition and language, then the sheet's Review. */
function drawScanPending(ctx) {
  clear(ctx.list);
  ctx.pending.forEach((card) => {
    if (!card.choices) card.choices = [];
    const qty = el("input", { type: "number", class: "col-qty-input", inputmode: "numeric", min: 1, max: 999, step: 1,
      value: String(card.quantity), "aria-label": `Copies of ${card.name}`,
      onchange: () => { card.quantity = Math.min(999, Math.max(1, parseInt(qty.value, 10) || 1)); qty.value = String(card.quantity); drawScanFoot(ctx); } });
    const finish = el("select", { "aria-label": `Finish of ${card.name}`,
      onchange: () => { card.finish = finish.value; colScanJoin(ctx, card); } },
      Object.entries(COL_FINISH_WORDS).map(([value, text]) => el("option", { value, text })));
    finish.value = card.finish;
    const condition = el("select", { "aria-label": `Condition of ${card.name}`,
      onchange: () => { card.condition = condition.value; colScanJoin(ctx, card); } },
      COL_CONDITIONS.map(([value, , text]) => el("option", { value, text })));
    condition.value = card.condition;
    // Language: as read off the card, else not recorded (blank, never assumed English).
    const languages = COL_LANGUAGES.some(([v]) => v === card.language) ? COL_LANGUAGES : [...COL_LANGUAGES, [card.language, card.language]];
    const language = el("select", { "aria-label": `Language of ${card.name}`,
      onchange: () => { card.language = language.value; colScanJoin(ctx, card); } },
      languages.map(([value, text]) => el("option", { value, text: value ? `${text} (${value})` : text })));
    language.value = card.language;
    ctx.list.append(el("li", { class: "col-trade-line" },
      el("span", { class: "col-trade-what", text: `${card.name} (${String(card.set).toUpperCase()} ${card.collector_number})` }),
      colScanPrinting(ctx, card),
      el("button", { type: "button", class: "btn btn-quiet", text: "Other printings…", "aria-label": `Other printings of ${card.name}`,
        onclick: () => colScanOther(ctx, card) }),
      qty, finish, condition, language,
      el("button", { type: "button", class: "btn btn-quiet", text: "Take out", "aria-label": `Take ${card.name} off the list`,
        onclick: () => { if (ctx.busy) return; ctx.pending.splice(ctx.pending.indexOf(card), 1); if (ctx.last === card) ctx.last = null; drawScanPending(ctx); } })));
  });
  if (!ctx.pending.length) ctx.list.append(el("li", { class: "sub", text: "Nothing yet." }));
  drawScanFoot(ctx);
}

function drawScanFoot(ctx) {
  const cards = ctx.pending.reduce((n, c) => n + c.quantity, 0);
  sheetActions(ctx.sheet, [{ text: "Cancel", value: "cancel", onclick: () => ctx.sheet.close() },
    cards || ctx.unsure.length ? { text: cards ? `Review ${plural(cards, "card")}` : "Review", kind: "primary", value: "review",
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
  if (ctx.busy || ctx.picking || !colScanHere(ctx)) return null;
  if (ctx.unsure.length) {
    colScanSay(ctx, "warn", `Resolve or skip ${plural(ctx.unsure.length, "photo")} in Check these before Review. Nothing was sent to the import preview.`);
    ctx.checks.focus(); return null;
  }
  if (!ctx.pending.length) return null;
  const cv = ctx.cv, text = colScanCsv(ctx.pending);
  const d = new Date();
  const day = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  ctx.sheet.close();
  const importing = openImportSheet(cv);
  if (importing) {
    importing.scanned = colScanCopy(ctx.pending);
    previewImport(importing, `scan-${day}.csv`, text);
  }
  return importing;
}

/** The import sheet's way back to a scan's pending list, to fix it (null for a file's import). */
function colScanBack(importing) {
  if (!importing.scanned) return null;
  return { text: "Back to the scanned list", value: "back", onclick: () => {
    if (importing.busy || importing.sheet.closed) return;
    importing.sheet.close();
    openScanSheet(importing.cv, importing.scanned);
  } };
}
