/* The Tokens page's "Scan token cards…" (E7-S32): photograph one token card at a time with the phone's camera (the
 * file input's capture), shrink the photo as the Collection page's Scan cards does (collection-scan.js colScanShrink)
 * and send it to POST /api/tokens/scan, which reads it on the PC and answers the token, emblem or reminder faces it
 * may be (nothing is written, no photo kept). A face read with a printing that has it, or a face read alone, goes
 * straight onto the pending list; otherwise the visitor picks one, or types the token's name (checked against
 * Scryfall's face names, the GET's face_names). Each pending card has its front (a face name), a back that stays
 * blank, "not recorded", until it's chosen or typed (never inferred: a double-faced printing's other face is only
 * offered as a button), "Single-sided (checked)" for a blank back, its copies, and a printing only when the photo read
 * one or one is chosen from those offered ("Not recorded" otherwise). Details and finish are never asked: they stay
 * blank. Cards that are the same front, back and printing join. "Review" shows the list; "Add" sends it to
 * POST /api/tokens/scan/add as one change, each row kept apart from any row already naming that card (the page never
 * merges rows). A list changed since keeps the pending cards and asks to add them again to the list as it is now.
 * Only where the visitor may change the tokens (view.canEdit), and every answer is checked against the page that
 * asked (tokensActive). */
"use strict";

const TOK_SCAN_CHOICES = 8;             // printings offered at most for one card
const TOK_SCAN_MAX = 50;                // rows added at once (the server's token_ops.MAX_BATCH)

/** Open the sheet over the Tokens page's view (where the visitor may change its tokens). Returns its context, or null. */
function openTokenScan(view, pending = []) {
  if (!tokensActive(view) || view.busy || !view.canEdit) return null;
  const sheet = openSheet(view.space === HOME_SPACE ? "Scan token cards" : `Scan token cards into ${spaceName(view.space)}'s tokens`,
    { wide: true });
  const id = (key) => `tok-scan-${key}-${sheet.heading.id}`;
  const ctx = { view, sheet, pending: tokScanCopy(pending), busy: false, seq: 0, last: null, reviewing: false,
    names: (view.data && view.data.face_names) || [] };
  ctx.input = el("input", { id: id("photo"), type: "file", accept: "image/*", capture: "environment", class: "col-file" });
  ctx.input.addEventListener("change", () => {
    const file = ctx.input.files && ctx.input.files[0];
    if (file) scanTokenPhoto(ctx, file);
  });
  ctx.listId = id("names");
  const datalist = el("datalist", { id: ctx.listId }, ctx.names.map((name) => el("option", { value: name })));
  ctx.name = el("input", { id: id("name"), type: "text", list: ctx.listId, autocomplete: "off", spellcheck: "false",
    autocapitalize: "words", placeholder: "e.g. Treasure" });
  ctx.name.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); addTypedToken(ctx); } });
  ctx.message = el("div", { class: "tok-sheet-message", role: "status", "aria-live": "polite" });
  ctx.result = el("div", { class: "col-scan-result" });
  ctx.list = el("ul", { class: "col-trade-list tok-scan-pending" });
  ctx.picking = el("div", {},
    el("p", { text: "Photograph one token card at a time, filling the frame with it. Each photo is read on the PC and "
      + "never kept. Nothing is added until you review the list." }),
    el("label", { class: "field col-file-field", for: ctx.input.id }, el("span", { text: "Take a photo of a token card" }), ctx.input),
    ctx.result,
    el("div", { class: "col-scan-typed" },
      el("label", { class: "field", for: ctx.name.id }, el("span", { text: "Or type a token's name" }), ctx.name),
      el("button", { type: "button", class: "btn", text: "Add it", onclick: () => addTypedToken(ctx) })),
    el("h3", { text: "To add" }), ctx.list);
  ctx.review = el("div", { hidden: true });
  sheet.body.append(datalist, ctx.message, ctx.picking, ctx.review);
  drawTokenScanPending(ctx);
  return ctx;
}

function tokScanSay(ctx, kind, text) {
  clear(ctx.message);
  if (text) ctx.message.append(el("p", { class: `box box-${kind}`, role: kind === "info" ? null : "alert", text }));
}

function tokScanHere(ctx, seq) {
  return !ctx.sheet.closed && tokensActive(ctx.view) && (seq === undefined || seq === ctx.seq);
}

/** Send one photo and show what it was read as. */
async function scanTokenPhoto(ctx, file) {
  if (ctx.busy || !tokScanHere(ctx)) return;
  const seq = ++ctx.seq;
  ctx.busy = true;
  ctx.input.disabled = true;
  clear(ctx.result);
  clear(ctx.message).append(loadingBox("Reading the token card…"));
  try {
    const photo = await colScanShrink(file);
    if (!tokScanHere(ctx, seq)) return;
    const answer = await apiWrite("/api/tokens/scan", tokBody(ctx.view, { photo }));
    if (!tokScanHere(ctx, seq)) return;
    drawTokenScanResult(ctx, answer);
  } catch (error) {
    if (tokScanHere(ctx, seq)) tokScanSay(ctx, "crit", error.message);
  } finally {
    if (seq === ctx.seq) { ctx.busy = false; ctx.input.disabled = false; ctx.input.value = ""; }
  }
}

/** "Fish (TBLB 7)", or "Treasure (printing not read)". */
function tokScanLabel(p) {
  return p.set ? `${p.front} (${String(p.set).toUpperCase()} ${p.collector_number})` : `${p.front} (printing not read)`;
}

/** One answer: a face read with a printing that has it, or read alone, is added (the others offered instead); else the
 * choices to pick from (a printing whose faces aren't the name read, or reprints of the face sharing the number). */
function drawTokenScanResult(ctx, answer) {
  const proposals = (answer.proposals || []).slice(0, TOK_SCAN_CHOICES);
  clear(ctx.result);
  if (!proposals.length) {
    tokScanSay(ctx, "warn", answer.message || "The token card couldn't be read.");
    ctx.result.append(el("p", { class: "sub", text: "Type its name below, or take the photo again closer and sharper." }));
    ctx.name.focus();
    return;
  }
  const [first, second] = proposals;
  const sure = first.how === "name and number" ? second?.how !== "name and number" : first.how === "name" && !second;
  ctx.last = sure ? addScanToken(ctx, first, proposals) : null;
  tokScanSay(ctx, sure ? "info" : "warn", sure ? `Added ${tokScanLabel(first)}.` : answer.message);
  const others = sure ? proposals.slice(1) : proposals;
  if (!others.length) return;
  ctx.result.append(el("p", { class: "sub", text: sure ? "Not that one? Choose instead:" : "Choose which this card is:" }),
    el("div", { class: "col-trade-choices", role: "group", "aria-label": "Token cards" }, others.map((p) =>
      el("button", { type: "button", class: "btn btn-quiet col-scan-pick", onclick: () => {
        if (ctx.busy || ctx.reviewing) return;
        if (sure && ctx.last) takeScanToken(ctx, ctx.last);
        ctx.last = addScanToken(ctx, p, proposals);
        clear(ctx.result);
        tokScanSay(ctx, "info", `Added ${tokScanLabel(p)}.`);
      } }, tokScanLabel(p)))));
}

/** The exact face name typed (any case or accents), or null; any name when the face names aren't to hand. */
function tokScanName(ctx, typed) {
  const text = String(typed || "").trim();
  if (!text) return null;
  if (!ctx.names.length) return text;
  const found = ctx.names.find((name) => tokFold(name) === tokFold(text));
  return found ? found.split(" // ")[0] : null;
}

/** "'Tresure' isn't a token, emblem or reminder name. Did you mean Treasure?" */
function tokScanUnknown(ctx, typed) {
  const hint = tokSuggest(typed, ctx.names);
  return `"${String(typed).trim()}" isn't a token, emblem or reminder name.${hint ? ` Did you mean ${hint}?` : ""}`;
}

/** A typed name: checked against the face names and added with no printing. */
function addTypedToken(ctx) {
  const typed = ctx.name.value.trim();
  if (ctx.busy || ctx.reviewing || !tokScanHere(ctx) || !typed) return;
  const front = tokScanName(ctx, typed);
  if (!front) { tokScanSay(ctx, "warn", tokScanUnknown(ctx, typed)); return; }
  ctx.seq++;          // an answer still on its way doesn't replace this
  clear(ctx.result);
  ctx.last = addScanToken(ctx, { front, faces: [front], set: "", collector_number: "", set_name: "" });
  tokScanSay(ctx, "info", `Added ${front}.`);
  ctx.name.value = "";
}

/** Pending cards copied, each with its own printing choices. */
function tokScanCopy(pending) {
  return pending.map((card) => ({ ...card, faces: [...(card.faces || [])], choices: (card.choices || []).map((c) => ({ ...c, faces: [...c.faces] })) }));
}

/** Add printings to a pending card's choices, each once: only printings with its front face. */
function tokScanAddChoices(card, printings) {
  for (const p of printings || []) {
    if (!p || !p.set || !(p.faces || []).some((f) => tokFold(f) === tokFold(card.front))
      || card.choices.some((c) => c.set === p.set && c.collector_number === p.collector_number)) continue;
    card.choices.push({ set: p.set, collector_number: p.collector_number, set_name: p.set_name || "", faces: [...p.faces] });
  }
}

/** Another pending card of the same front, back and printing, if any: the server's same card (its single-sided tick
 * only goes in the row's notes, so it doesn't make another). */
function tokScanSame(ctx, card) {
  return ctx.pending.find((c) => c !== card && c.front === card.front && c.back === card.back && c.set === card.set
    && c.collector_number === card.collector_number) || null;
}

/** Join a card's copies to the same one listed: single-sided stays ticked only when both were (every copy checked). */
function tokScanMerge(same, card) {
  same.quantity = Math.min(9999, same.quantity + card.quantity);
  same.single = Boolean(same.single) && Boolean(card.single);
  tokScanAddChoices(same, card.choices);
}

/** Put a token card on the pending list (one more copy when it's there), its back blank and not single-sided. */
function addScanToken(ctx, p, choices = [p]) {
  const card = { front: p.front, back: "", single: false, set: p.set || "", collector_number: p.set ? p.collector_number : "",
    faces: p.set ? [...p.faces] : [], quantity: 1, choices: [] };
  tokScanAddChoices(card, [p, ...choices]);
  const same = tokScanSame(ctx, card);
  if (same) {
    tokScanMerge(same, card);
    drawTokenScanPending(ctx);
    return same;
  }
  ctx.pending.push(card);
  drawTokenScanPending(ctx);
  return card;
}

/** After a change to a pending card, join it to the same one already listed; the list is drawn again either way. */
function tokScanJoin(ctx, card) {
  const same = tokScanSame(ctx, card);
  if (same) {
    tokScanMerge(same, card);
    ctx.pending.splice(ctx.pending.indexOf(card), 1);
    if (ctx.last === card) ctx.last = same;
  }
  drawTokenScanPending(ctx);
}

function takeScanToken(ctx, card) {
  if (card.quantity > 1) card.quantity -= 1;
  else ctx.pending.splice(ctx.pending.indexOf(card), 1);
  drawTokenScanPending(ctx);
}

/** What stops a pending card being added, or null: a name that isn't a face, or a printing without its front. */
function tokScanProblem(ctx, card) {
  if (!tokScanName(ctx, card.front)) return tokScanUnknown(ctx, card.front);
  if (card.back && !tokScanName(ctx, card.back)) return tokScanUnknown(ctx, card.back);
  if (card.set && card.faces.length && !card.faces.some((f) => tokFold(f) === tokFold(card.front))) {
    return `${String(card.set).toUpperCase()} ${card.collector_number} is ${card.faces.join(" / ")}, not ${card.front}.`;
  }
  return null;
}

/** A pending card's printing: "Not recorded", or one of the printings offered for its front. */
function tokScanPrinting(ctx, card) {
  const at = card.set ? String(card.choices.findIndex((c) => c.set === card.set && c.collector_number === card.collector_number)) : "";
  const select = el("select", { "aria-label": `Printing of ${card.front}`, onchange: () => {
    if (ctx.busy) { select.value = at; return; }
    const c = card.choices[parseInt(select.value, 10)];
    card.set = c ? c.set : "";
    card.collector_number = c ? c.collector_number : "";
    card.faces = c ? [...c.faces] : [];
    tokScanJoin(ctx, card);
  } }, el("option", { value: "", text: "Printing not recorded" }),
  card.choices.map((c, i) => el("option", { value: String(i),
    text: [`${String(c.set).toUpperCase()} ${c.collector_number}`, c.set_name && c.set_name.toUpperCase() !== String(c.set).toUpperCase()
      ? c.set_name : null].filter(Boolean).join(" · ") })));
  select.value = at === "-1" ? "" : at;
  return select;
}

/** A pending card's back: blank (not recorded) unless typed, or chosen from its printing's other face. */
function tokScanBack(ctx, card) {
  const input = el("input", { type: "text", list: ctx.listId, autocomplete: "off", spellcheck: "false", value: card.back,
    placeholder: "Back: not recorded", "aria-label": `Back of ${card.front}`, onchange: () => {
      const typed = input.value.trim();
      card.back = typed ? (tokScanName(ctx, typed) || typed) : "";
      if (card.back) card.single = false;
      tokScanJoin(ctx, card);
    } });
  const other = card.back ? null : card.faces.find((f) => tokFold(f) !== tokFold(card.front));
  const single = el("input", { type: "checkbox", "aria-label": `${card.front} is single-sided (checked)`, onchange: () => {
    card.single = single.checked;
    tokScanJoin(ctx, card);
  } });
  single.checked = Boolean(card.single);
  return [input,
    other ? el("button", { type: "button", class: "btn btn-quiet", text: `Back: ${other}`, "aria-label": `Back of ${card.front} is ${other}`,
      onclick: () => { if (ctx.busy) return; card.back = other; card.single = false; tokScanJoin(ctx, card); } }) : null,
    card.back ? null : el("label", { class: "tok-scan-single" }, single, " Single-sided (checked)")];
}

/** The pending list, each card with its front, back, printing and copies, then the sheet's Review. */
function drawTokenScanPending(ctx) {
  clear(ctx.list);
  ctx.pending.forEach((card) => {
    const qty = el("input", { type: "number", class: "col-qty-input", inputmode: "numeric", min: 1, max: 9999, step: 1,
      value: String(card.quantity), "aria-label": `Copies of ${card.front}`,
      onchange: () => { card.quantity = Math.min(9999, Math.max(1, parseInt(qty.value, 10) || 1)); qty.value = String(card.quantity); drawTokenScanFoot(ctx); } });
    const problem = tokScanProblem(ctx, card);
    ctx.list.append(el("li", { class: "col-trade-line" },
      el("span", { class: "col-trade-what", text: tokScanLabel(card) }),
      tokScanPrinting(ctx, card), ...tokScanBack(ctx, card), qty,
      el("button", { type: "button", class: "btn btn-quiet", text: "Take out", "aria-label": `Take ${card.front} off the list`,
        onclick: () => { if (ctx.busy) return; ctx.pending.splice(ctx.pending.indexOf(card), 1); if (ctx.last === card) ctx.last = null; drawTokenScanPending(ctx); } }),
      problem ? el("p", { class: "box box-warn", role: "alert", text: problem }) : null));
  });
  if (!ctx.pending.length) ctx.list.append(el("li", { class: "sub", text: "Nothing yet." }));
  if (ctx.pending.length > TOK_SCAN_MAX) {
    ctx.list.append(el("li", { class: "box box-warn", role: "alert",
      text: `At most ${TOK_SCAN_MAX} lines can be added at once: take some out, and add them afterwards.` }));
  }
  drawTokenScanFoot(ctx);
}

function drawTokenScanFoot(ctx) {
  const cards = ctx.pending.reduce((n, c) => n + c.quantity, 0);
  const blocked = ctx.pending.some((card) => tokScanProblem(ctx, card)) || ctx.pending.length > TOK_SCAN_MAX;
  sheetActions(ctx.sheet, [{ text: "Cancel", value: "cancel", onclick: () => ctx.sheet.close() },
    cards ? { text: `Review ${plural(cards, "token card")}`, kind: "primary", value: "review", disabled: blocked,
      onclick: () => reviewTokenScan(ctx) } : null]);
}

/** The rows POST /api/tokens/scan/add takes: a printing's number for the back only when the back is its other face. */
function tokScanRows(ctx) {
  return ctx.pending.map((card) => {
    const front = tokScanName(ctx, card.front), back = card.back ? tokScanName(ctx, card.back) : "";
    const backOnPrinting = back && card.set && card.faces.some((f) => tokFold(f) === tokFold(back));
    return { front, back, set: card.set, front_collector_number: card.set ? card.collector_number : "",
      back_collector_number: backOnPrinting ? card.collector_number : "", quantity: card.quantity, single_sided: !back && Boolean(card.single) };
  });
}

/** Review: the cards as they'll be added, and which are already listed (each is kept as a row of its own). */
function reviewTokenScan(ctx, note = null) {
  if (ctx.busy || !tokScanHere(ctx) || !ctx.pending.length) return;
  if (ctx.pending.some((card) => tokScanProblem(ctx, card))) return;
  ctx.reviewing = true;
  ctx.picking.hidden = true;
  ctx.review.hidden = false;
  const listed = (ctx.view.data && ctx.view.data.rows) || [];
  const rows = tokScanRows(ctx);
  clear(ctx.review).append(
    el("p", { text: `These ${plural(rows.reduce((n, r) => n + r.quantity, 0), "token card")} are added as one change. `
      + "Details and finish aren't recorded; a blank back stays to check unless you ticked it single-sided." }),
    el("ul", { class: "col-trade-list" }, rows.map((r) => {
      const same = listed.some((row) => tokFold(row.front) === tokFold(r.front) && tokFold(row.back) === tokFold(r.back));
      return el("li", {}, `${r.back ? `${r.front} / ${r.back}` : r.front} ×${r.quantity}`,
        r.set ? ` (${r.set.toUpperCase()} ${r.front_collector_number})` : "",
        r.single_sided ? " · single-sided" : "",
        same ? el("span", { class: "sub", text: " · already listed: added as a row of its own" }) : null);
    })));
  if (note) tokScanSay(ctx, "warn", note);
  else clear(ctx.message);
  sheetActions(ctx.sheet, [{ text: "Back to the list", value: "back", onclick: () => backToTokenScan(ctx) },
    { text: `Add ${plural(rows.reduce((n, r) => n + r.quantity, 0), "token card")}`, kind: "primary", value: "add",
      onclick: () => addTokenScan(ctx) }]);
}

function backToTokenScan(ctx) {
  if (ctx.busy) return;
  ctx.reviewing = false;
  ctx.review.hidden = true;
  ctx.picking.hidden = false;
  clear(ctx.message);
  drawTokenScanPending(ctx);
}

/** Add the reviewed list as one change; a list changed meanwhile is shown as it is now and the review asked again. */
async function addTokenScan(ctx) {
  if (ctx.busy || !tokScanHere(ctx)) return;
  const view = ctx.view, seq = ++ctx.seq;
  ctx.busy = true;
  setTokensBusy(view, true);
  clear(ctx.message).append(loadingBox("Adding the token cards…"));
  try {
    const answer = await apiWrite("/api/tokens/scan/add", tokBody(view, { sha256: view.data.sha256, rows: tokScanRows(ctx) }));
    if (!tokensActive(view)) return;
    ctx.sheet.close();
    tokShow(view, answer.data, `Added ${plural(answer.added.cards, "token card")}.`, answer.warnings, "add");
  } catch (error) {
    if (!tokensActive(view)) return;
    setTokensBusy(view, false);
    const latest = error.data && error.data.latest;
    if (error.status === 409 && latest) {
      tokShow(view, latest, "This is the tokens list as it is now.");
      if (seq === ctx.seq && !ctx.sheet.closed) { ctx.busy = false; reviewTokenScan(ctx, `${error.message} Check the list and add them again.`); }
      return;
    }
    if (!ctx.sheet.closed) tokScanSay(ctx, "crit", error.message);
  } finally {
    if (seq === ctx.seq) ctx.busy = false;
  }
}
