/* One read-only box difference leads to the ordinary guarded Collection editor. */
"use strict";

let boxCollectionHandoff = null;

/** Close first, then wait for this exact sheet entry to land before another route or sheet. */
function boxCollectionAfterSheet(sheet, guard, go) {
  const entry = sheet.entry;
  let done = false, closed = false;
  const stop = () => {
    window.removeEventListener("popstate", landed); window.removeEventListener("hashchange", abandoned);
    sheet.dialog.removeEventListener("close", afterClose);
  };
  const finish = () => {
    if (done) return;
    done = true; stop();
    if (guard() && !document.querySelector("dialog[open]")) go();
  };
  const abandoned = () => { done = true; stop(); };
  const landed = () => {
    if (!guard() || entry && (history.state?.sheet === entry.token || history.state?.pos !== entry.pos - 1)) { abandoned(); return; }
    finish();
  };
  function afterClose() {
    if (closed || !sheet.closed) return;
    closed = true;
    if (!guard()) { abandoned(); return; }
    if (!entry || entry.fromHistory || history.state?.sheet !== entry.token) landed();
    else { window.addEventListener("popstate", landed); window.addEventListener("hashchange", abandoned); }
  }
  sheet.dialog.addEventListener("close", afterClose);
  sheet.close();
  afterClose();
}

function boxCollectionScope() {
  return Boolean(state.profile?.id) && ownSpace() === HOME_SPACE && seesHomeInventory(state.may) && canEditSpace(HOME_SPACE);
}

function boxCollectionDifference(deck, evidence, row, direction) {
  const text = value => typeof value === "string" && value === value.trim() && value.length > 0 && value.length <= 200
    && !/[\u0000-\u001f\u007f]/.test(value);
  if (!boxCollectionScope() || !deck || !/^(casual|commander)\/[^/]+$/.test(deck.id) || !text(deck.title)
      || !evidence || !/^[a-f0-9]{64}$/.test(evidence.meta?.expect || "") || !/^[a-f0-9]{64}$/.test(evidence.meta?.recipe_sha256 || "")
      || !["missing", "extra"].includes(direction) || !row || !BOX_CHECK_SECTIONS.includes(row.section)
      || !["card", "marker"].includes(row.kind) || !text(row.name) || !Number.isSafeInteger(row.quantity) || row.quantity < 1 || row.quantity > 9999
      || row.kind === "marker" && !text(row.for) || row.kind === "card" && row.for !== null) return null;
  return Object.freeze({ id: deck.id, title: deck.title, deck_sha256: evidence.meta.expect, recipe_sha256: evidence.meta.recipe_sha256,
    section: row.section, kind: row.kind, name: row.name, for: row.for, quantity: row.quantity, direction });
}

/** Provenance only: collection writes always use their own freshly loaded SHA. */
function boxCollectionNavigate(difference) {
  boxCollectionHandoff = { difference, profile: state.profile, route: null };
  location.hash = "#/collection";
}

/** A different person, address or second arrival discards the receipt. */
function boxCollectionRoute(path, token) {
  const handoff = boxCollectionHandoff;
  if (!handoff) return;
  if (!boxCollectionScope() || handoff.profile !== state.profile || path !== "collection" || location.hash !== "#/collection"
      || handoff.route !== null) { boxCollectionHandoff = null; return; }
  handoff.route = token;
}

function boxCollectionNotice(difference) {
  return el("div", { class: "box box-info box-collection-context" },
    el("p", {}, el("strong", { text: difference.title }), ": ", difference.section, "; ",
      difference.direction === "missing" ? "missing " : "extra ", plural(difference.quantity, "physical card"), ": ",
      packBoxRowWords(difference), "."),
    el("p", { text: "This is a box observation, not a collection adjustment. The cards may still be in storage or another box. Check every location, choose the actual printing, then enter its total owned copies." }),
    el("p", { class: "sub", text: "Plain basic lands aren't tracked here; record only special printings, such as full-art or foil basics." }));
}

function boxCollectionRows(rows) {
  if (!Array.isArray(rows)) return false;
  const keys = new Set();
  for (const row of rows) {
    if (!row || typeof row !== "object" || ["name", "set", "collector_number", "finish"].some(key => typeof row[key] !== "string" || !row[key])
        || !/^\d+$/.test(String(row.quantity)) || !Number.isSafeInteger(Number(row.quantity)) || Number(row.quantity) < 1) return false;
    const key = colKey(row); if (keys.has(key)) return false; keys.add(key);
  }
  return true;
}

function boxCollectionPrintings(answer, name) {
  return answer?.name === name && Array.isArray(answer.printings) && answer.printings.every(row => row && typeof row === "object"
    && typeof row.set === "string" && Boolean(row.set) && typeof (row.collector_number ?? row.number) === "string"
    && Boolean(row.collector_number ?? row.number) && Array.isArray(row.finishes) && row.finishes.length > 0
    && row.finishes.every(finish => ["nonfoil", "foil", "etched"].includes(finish)));
}

/** A successful fresh Collection load consumes this once; no URL, roster or storage carries it. */
async function boxCollectionConsume(cv) {
  const handoff = boxCollectionHandoff;
  if (!handoff) return;
  boxCollectionHandoff = null;
  if (handoff.route !== cv.token || handoff.profile !== state.profile || !boxCollectionScope() || !colActive(cv)
      || cv.space !== HOME_SPACE || !cv.editable || cv.unsupported || location.hash !== "#/collection") return;
  const hash = location.hash, profile = state.profile;
  const here = () => colActive(cv) && state.profile === profile && boxCollectionScope() && cv.space === HOME_SPACE
    && cv.editable && location.hash === hash && parseHash().path === "collection";
  await boxCollectionCheckSource(cv, handoff.difference, here);
}

/** The box review's deck is still the one it checked, then the copies sheet; else why not, with the way back
 * to Build decks (and Try again when the PC couldn't answer). */
async function boxCollectionCheckSource(cv, difference, here) {
  const waiting = loadingBox("Checking the box review's deck…", { small: true });
  clear(cv.message).append(waiting);
  const back = () => el("a", { class: "btn btn-quiet", href: "#/assembly", text: "Back to Build decks" });
  try {
    const source = await api(`/api/deck/edit?id=${encodeURIComponent(difference.id)}`);
    if (!here()) return;
    if (source?.id !== difference.id || source.sha256 !== difference.deck_sha256) {
      colSay(cv, "The deck changed after this box review. Open a fresh box check before reviewing its collection copies.");
      cv.message.append(el("div", { class: "actions" }, back()));
      return;
    }
  } catch (error) {
    if (!here()) return;
    colSay(cv, "The source deck couldn't be checked. Open a fresh box check before reviewing its collection copies.");
    const retry = error instanceof ApiError && (error.status === 0 || error.status >= 500);
    cv.message.append(el("div", { class: "actions" }, retry ? el("button", { type: "button", class: "btn", text: "Try again",
      onclick: () => { if (here()) boxCollectionCheckSource(cv, difference, here); } }) : null, back()));
    return;
  } finally { waiting.remove(); }
  openCopiesSheet(cv, difference.name, { repair: Object.freeze({ difference, here }) });
}

function boxCollectionEditorHere(ctx) { return !ctx.boxRepair || ctx.boxRepair.here(); }

function boxCollectionEditorNote(ctx) {
  if (!ctx.boxRepair) return;
  ctx.sheet.body.insertBefore(boxCollectionNotice(ctx.boxRepair.difference), ctx.form);
  ctx.inputs.name.readOnly = true; ctx.inputs.name.setAttribute("readonly", "");
  ctx.inputs.quantity.value = "";
  ctx.inputs.quantity.setAttribute("aria-label", "Total owned copies of this printing");
  const label = ctx.form.querySelector(".col-field-quantity")?.querySelector("label");
  if (label) label.textContent = "Total owned copies of this printing";
}
