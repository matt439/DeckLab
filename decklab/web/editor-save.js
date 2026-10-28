/* Deck Lab's editor: checking the draft and saving it (Milestone 4).

Loaded after editor.js, editor-screen.js, editor-details.js, editor-lines.js and editor-cards.js and
before editor-deckpage.js (then matchups.js and the page's other scripts, core.js to app.js). It uses
editor.js's constants, `editor`, the list and field model, rebase(), drafts and sheets, editor-lines.js's
sectionTitle and drawLines, and editor-screen.js's drawing (drawEditor, drawBanners, drawBar, changed,
noOwnedList), its question before
discarding (askDiscardChanges) and its words and buttons for a deck deleted since it was loaded (GONE_TITLE,
GONE_WORDS, goneActions, goneFrom).

Checks: each change goes to /api/deck/check after a short pause, for the deck rules' warnings, what
blocks a save, a Commander deck's bracket and the owned-vs-needed preview. The running card count is
worked out on the page, so it follows every tap at once.

Saving: Save (or Ctrl/Cmd+S) checks the draft and, when nothing blocks it and the deck hasn't changed
since, POSTs /api/deck/save (or /api/decks for a new deck) at once and stays in the editor, with a toast
(and a note listing other decks whose tables are now out of date, with "Update their tables"). The
review sheet (what changes, the warnings and what saving does) comes up only for blocks, a deck that
changed since, or an error. "Save & view deck" (the split button's menu) opens the deck afterwards,
with a box saying what was saved (savedBox, in editor-deckpage.js). The server rewrites the deck's
owned-vs-needed table and saves it in Deck Lab. The write-up (the Notes tab) and "Mark write-up as
current" go with the same save (prose, mark_current). A 409 means the deck changed after it was loaded (or was
deleted): the page offers to load the latest version and re-apply the changes made here (per-card
quantity differences by section and printing, and the header fields changed), or to discard them
(discardChanges, which only editor-screen.js's askDiscardChanges calls, once the person has said so).
*/
"use strict";

const CHECK_DELAY = 450;        // ms after the last change before the draft is checked

/** Async writes/reloads stay with their original page, frame, profile and optional review sheet. */
function editorWriteOwner(ed, sheet = null) {
  const token = routeToken, page = ed?.dom?.page, frame = JSON.stringify([ed?.id, ed?.version, ed?.space, ed?.mode]);
  return () => !!(ed && editor === ed && !ed.leaving && !ed.readOnly && ed.profile === state.profile?.id
    && token === routeToken && page === ed.dom?.page && (!page || page.isConnected)
    && frame === JSON.stringify([ed.id, ed.version, ed.space, ed.mode])
    && (!sheet || !sheet.closed && (!sheet.dialog || sheet.dialog.isConnected && keyboardDialog() === sheet.dialog)));
}


// Checking ---------------------------------------------------------------------------

/** The request body for /api/deck/check, /api/deck/save and /api/decks (with the title added). */
function draftBody() {
  const ed = editor;
  if (ed.mode === "new") {
    const body = { lists: { target: sendList(ed.lists) }, fields: newDeckFields() };
    if (ed.from) body.from = ed.from;
    else body.kind = ed.fields.kind;
    if (ed.space && ed.space !== HOME_SPACE) body.space = ed.space;
    return body;
  }
  const body = { id: ed.id, sha256: ed.sha256 };
  if (listChanged()) body.lists = { [ed.version]: sendList(ed.lists) };
  if (editorConsideringSupported(ed) && editorConsideringChanged(ed)) {
    (body.lists || (body.lists = {})).considering = ed.considering.map(sendLine);
  }
  addEditorPromotionBody(body, ed);
  const fields = changedFields();
  if (Object.keys(fields).length) body.fields = fields;
  const prose = changedProse();
  if (Object.keys(prose).length) body.prose = prose;
  if (ed.markCurrent) body.mark_current = true;
  // Taking every card out of a deck is a block until the person says it's meant ("Empty the deck anyway").
  if (ed.confirmEmpty && body.lists?.target && ed.version === "target" && !Object.keys(body.lists.target).length) {
    body.confirm_empty = true;
  }
  return body;
}

/** {section: [uid]} in the order a body's list sends them, to find the line a block is about. */
function sentUids(body) {
  const list = body.lists && (body.lists[editor.mode === "new" ? "target" : editor.version]);
  const out = {};
  if (body.lists?.considering) out.considering = editor.considering.map(l => l.uid);
  if (editor.version === "owned" && body.lists?.target && editor.planned) {
    out.planned = Object.fromEntries(Object.entries(editor.planned).map(([s, lines]) => [s, lines.map(l => l.uid)]));
  }
  if (!list) return out;
  for (const section of Object.keys(list)) out[section] = editor.lists[section].map((l) => l.uid);
  return out;
}

function scheduleCheck(delay = CHECK_DELAY) {
  const ed = editor;
  ed.checkSeq += 1;              // a reply for the previous draft cannot repaint this one
  ed.checking = true;
  showRowAvailability(null);
  drawCheckingState();
  clearTimeout(ed.checkTimer);
  ed.checkTimer = setTimeout(() => runCheck(ed), delay);
}

/** Check the draft now; the answer, or null (an error, or a newer check replaced it: then info.superseded
 * is set). */
async function runCheck(ed = editor, info = {}) {
  if (!ed || editor !== ed) return null;
  const token = routeToken;
  clearTimeout(ed.checkTimer);
  const seq = ++ed.checkSeq;
  const body = draftBody();
  const sent = sentUids(body);
  ed.checking = true;
  drawCheckingState();
  try {
    const answer = await apiWrite("/api/deck/check", body);
    if (editor === ed && seq !== ed.checkSeq) info.superseded = true;
    if (editor !== ed || seq !== ed.checkSeq || token !== routeToken || ed.profile !== state.profile?.id || ed.leaving) return null;
    const wasChanged = ed.check && ed.check.file_changed;
    const wasGone = !!ed.gone;
    Object.assign(ed, { check: answer, sent, checkError: null, checking: false, gone: null });
    fillCards(answer, sent);
    if (answer.brackets && answer.brackets.length && !ed.brackets.length) {
      ed.brackets = answer.brackets;
      const select = document.getElementById("f-target_bracket");
      if (select) for (const option of select.options) {
        const b = ed.brackets.find((x) => String(x.number) === option.value);
        if (b) option.textContent = `${b.number}: ${b.name}`;
      }
    }
    drawCheck();
    drawBar();
    markRows();
    if (Boolean(answer.file_changed) !== Boolean(wasChanged) || wasGone) drawBanners();
    return answer;
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    if (editor === ed && seq !== ed.checkSeq) info.superseded = true;
    if (editor !== ed || seq !== ed.checkSeq || token !== routeToken || ed.profile !== state.profile?.id || ed.leaving) return null;
    const wasGone = !!ed.gone;
    // A deck deleted since it was loaded: the banner says so, with what can be done.
    Object.assign(ed, { checkError: e, checking: false, gone: goneFrom(e) });
    drawCheck();
    drawBar();
    if (wasGone !== !!ed.gone) drawBanners();
    return null;
  }
}

/** Lines that came without card data (a precon's, a draft's) take it from the check's answer, which has the
 * lists as they'd be saved, line for line as sent. */
function fillCards(answer, sent) {
  const ed = editor;
  fillEditorConsideringCards(answer, sent);
  const lists = answer.lists && answer.lists[ed.mode === "new" ? "target" : ed.version];
  if (!lists) return;
  let filled = false;
  for (const [section, uids] of Object.entries(sent || {})) {
    if (!Array.isArray(uids)) continue;
    (uids || []).forEach((uid, i) => {
      const found = findLine(uid);
      const line = found && found.line;
      const answered = (lists[section] || [])[i];
      if (line && !line.card && answered && answered.card && answered.name === line.name) {
        line.card = answered.card;
        filled = true;
      }
    });
  }
  if (filled) { drawLines(); drawStats(); drawEditorHeaderIdentity(ed); }
}

/** The availability of the list being edited, from the last check (null while there's none). */
function currentAvailability() {
  const ed = editor;
  const a = ed && ed.check;
  if (!a || ed.checkError) return null;
  const version = ed.mode === "new" ? "target" : ed.version;
  return a.availability ? a.availability[version] : version === "target" ? a.owned : null;
}

function drawCheckingState() {
  const ed = editor;
  const label = ed.dom.check && ed.dom.check.querySelector(".checking-now");
  if (label) label.hidden = !ed.checking;
  if (!ed.check) drawBar();
}

function drawCheck() {
  const ed = editor;
  const host = ed.dom.check;
  if (!host) return;
  showRowAvailability(null);
  clear(host);
  const a = ed.check;
  host.append(el("h2", { id: "h-check", class: ed.dom.panes?.wide ? "edit-pane-heading" : ed.dom.sideBody ? "sr-only" : null }, "Checks",
    el("span", { class: "checking-now sub", hidden: !ed.checking || null }, el("span", { class: "spinner spinner-small", "aria-hidden": "true" }), "checking")));
  if (ed.gone) {
    host.append(el("p", { class: "sub", text: "Not checked: this deck was deleted since you opened it (see the note at the top)." }),
      el("div", { class: "actions" }, el("button", { type: "button", class: "btn", text: "Check again", onclick: () => runCheck() })));
    return;
  }
  if (ed.checkError) {
    host.append(el("div", { class: "box box-crit" },
      el("p", { text: `The deck couldn't be checked: ${ed.checkError.message}` }),
      el("div", { class: "actions" }, el("button", { type: "button", class: "btn", text: "Check again", onclick: () => runCheck() }))));
    return;
  }
  if (!a) {
    host.append(loadingBox("Checking the deck…"));
    return;
  }
  const title = typedTitleProblem();
  const blocks = [...(title ? [{ field: "title", problem: title }] : []), ...a.blocks];
  const version = ed.mode === "new" ? "target" : ed.version;
  const availability = currentAvailability();
  host.append(checkSummary(availability, blocks.length, emptyList() ? 0 : a.warnings.length));
  if (blocks.length) host.append(blocksBox(blocks, () => { editor.confirmEmpty = true; runCheck(); }));
  if (emptyList()) {
    // Nothing to say until there are cards (the summary says so).
  } else if (a.warnings.length) {
    host.append(el("div", { class: "box box-warn" },
      el("h3", { text: `${plural(a.warnings.length, "thing")} worth a look` }),
      warningList(a)));
  } else if (noOwnedList()) {
    host.append(el("p", { class: "sub", text: `There's no ${listName("owned", true)} to check yet.` }));
  }
  if (a.bracket) host.append(bracketBox(a.bracket));
  // The missing cards and what they cost; nothing when every card is here (the summary says so).
  if (availability && !emptyList() && availability.totals.missing) host.append(ownedPreview(availability, version));
  showRowAvailability(availability);
  drawSideTabs();
}

/** The Checks tab's first line: "3 missing · ~A$4.20", "1 problem", "2 warnings", or that it's all here. */
function checkSummary(o, blocks, warnings) {
  const t = o && o.totals;
  const bits = [];
  if (t && t.missing) bits.push(`${t.missing} missing` + (o.price_error || t.aud_missing == null ? "" : ` · ~${aud(t.aud_missing)}`));
  if (blocks) bits.push(plural(blocks, "problem"));
  if (warnings) bits.push(plural(warnings, "warning"));
  if (!bits.length) {
    return el("p", { class: "check-summary" }, emptyList() ? "Nothing to check yet."
      : t ? "Every card is here or on the way, and the list follows the deck-building rules."
        : "The list follows the deck-building rules.");
  }
  return el("p", { class: "check-summary" }, el("b", { text: bits.join(" · ") }));
}

/** Each row's one badge, when its card isn't simply owned and free: "2 missing" (and, in its tooltip, the decks
 * holding copies), or "On the way". Nothing for a card that's here. */
function showRowAvailability(availability) {
  const ed = editor;
  if (!ed || !ed.dom.lines) return;
  for (const row of ed.dom.lines.querySelectorAll(".edit-row[data-uid]")) {
    const previous = row.querySelector(".edit-availability");
    if (previous) previous.remove();
    const found = findLine(Number(row.dataset.uid));
    const supply = found && availability && availability.rows.find((r) => r.name === found.line.name);
    if (!supply) continue;
    const held = supply.in_use_elsewhere.reduce((n, [, qty]) => n + qty, 0);
    const where = supply.in_use_elsewhere.map(([deck, qty]) => `${qty} in use in ${deck}`).join("; ");
    let badge = null;
    if (supply.missing > 0) {
      badge = status("warn", held && supply.missing <= held ? `${supply.missing} in other decks` : `${supply.missing} missing`);
      badge.title = [`${supply.missing} missing for this list`, where].filter(Boolean).join("; ");
    } else if (supply.on_the_way > 0 && supply.owned - supply.on_the_way - held < supply.need) {
      badge = status("info", "On the way");
      badge.title = (supply.on_the_way_from || []).map(([from, qty]) => `${qty}${from ? ` from ${from}` : " on the way"}`).join("; ");
    }
    if (!badge) continue;
    badge.setAttribute("class", `${badge.getAttribute("class")} edit-availability`);
    const slot = row.querySelector(".edit-badge-slot") || row;
    slot.append(badge);
  }
}

const OWNED_PREFIX = "Play-now list: ";      // how the server (api/drafts.py) starts the play-now list's warnings

/** The check's warnings, each with the cards it's about ({text, names, mine}): "warning_cards" gives the
 * exact names ([] for a warning about the deck as a whole). mine: the warning is about the list being
 * edited (the play-now list's start with "Play-now list: ", which comes off the text there). */
function checkWarnings(a) {
  const ed = editor;
  const warnings = a.warnings || [];
  const cards = Array.isArray(a.warning_cards) && a.warning_cards.length === warnings.length ? a.warning_cards : null;
  const owned = ed && ed.mode === "edit" && ed.version === "owned";
  return warnings.map((w, i) => {
    const forOwned = w.startsWith(OWNED_PREFIX);
    return { text: owned && forOwned ? capitalise(w.slice(OWNED_PREFIX.length)) : w,
      names: (cards && Array.isArray(cards[i]) ? cards[i] : []).filter((n) => typeof n === "string"),
      mine: owned === forOwned };
  });
}

/** The check's warnings as a list, each with buttons that jump to the cards it's about in the list being
 * edited. The owned-only editor groups them by the list they're about; the rest are about the target list
 * or the deck as a whole. onJump: what a jump does first (the review closes its sheet). */
function warningList(a, onJump) {
  const warnings = checkWarnings(a);
  const item = (w) => {
    const names = w.mine ? w.names.filter((name) => rowsNamed(name).length) : [];
    return el("li", {}, w.text, names.length ? el("span", { class: "warn-jumps" },
      el("span", { class: "warn-jumps-label", text: "Show in the list:" }),
      names.map((name) => el("button", { type: "button", class: "chip-btn warn-jump", "aria-label": `Show ${name} in the list`,
        onclick: () => { if (onJump) onJump(); jumpToCard(name); } }, name))) : null);
  };
  const items = (list) => el("ul", { class: "warn-list" }, list.map(item));
  const ed = editor;
  if (!ed || ed.mode !== "edit" || ed.version !== "owned") return items(warnings);
  const mine = warnings.filter((w) => w.mine);
  const rest = warnings.filter((w) => !w.mine);
  if (!rest.length) return items(mine);
  return el("div", { class: "warn-groups" },
    mine.length ? [el("h4", { class: "warn-group", text: `This list (the ${listName("owned", true)})` }), items(mine)] : null,
    el("h4", { class: "warn-group", text: `The ${listName("target", true)}, and the deck as a whole` }), items(rest));
}

/** The rows on the page for a card name, in the order they're shown. */
function rowsNamed(name) {
  const ed = editor;
  if (!ed || !ed.dom.lines) return [];
  return [...ed.dom.lines.querySelectorAll(".edit-row[data-uid]")].filter((row) => {
    const found = findLine(Number(row.dataset.uid));
    return found && found.line.name === name;
  });
}

/** Show a card's row: scroll to it, light it up and put the focus on its printing chip. A second jump to
 * the same card goes on to its next row (a card on two lines, or in the deck and the sideboard). */
function jumpToCard(name) {
  const rows = rowsNamed(name);
  if (!rows.length) {
    toast(`${name} isn't in the list any more.`);
    return;
  }
  const ed = editor;
  const at = ed.jumped && ed.jumped.name === name ? (ed.jumped.at + 1) % rows.length : 0;
  ed.jumped = { name, at };
  const row = rows[at];
  row.scrollIntoView({ block: "center" });
  row.classList.remove("flash");
  void row.offsetWidth;            // start the animation again
  row.classList.add("flash");
  const chip = row.querySelector(".chip-btn");
  if (chip) chip.focus({ preventScroll: true });
}

/** What stops a save. confirmEmpty: what "Empty the deck anyway" does, for the block that asks for it. */
function blocksBox(blocks, confirmEmpty) {
  const asks = confirmEmpty && blocks.some((b) => b.confirm === "confirm_empty");
  return el("div", { class: "box box-crit" },
    el("h3", { text: "This can't be saved yet" }),
    el("ul", {}, blocks.map((b) => el("li", {},
      b.field ? `${FIELD_WORDS[b.field] || b.field}: ` : b.list === "considering" ? "Considering: " : b.section ? `${b.section}: ` : "", b.problem))),
    asks ? el("div", { class: "actions" }, el("button", { type: "button", class: "btn btn-danger",
      text: "Empty the deck anyway", onclick: confirmEmpty })) : null);
}

/** Mark the rows a block is about (the check's index is the line's place in what was sent), then the
 * rows a warning about this list names ("warning_cards"), each with what it says. */
function markRows() {
  const ed = editor;
  markEditorConsideringRows();
  if (!ed.dom.lines) return;
  for (const row of ed.dom.lines.querySelectorAll(".edit-row.is-blocked, .edit-row.is-warned")) {
    row.classList.remove("is-blocked", "is-warned");
    row.querySelectorAll(".edit-block, .edit-warn").forEach((p) => p.remove());
  }
  if (!ed.check) return;
  const list = ed.mode === "new" ? "target" : ed.version;
  for (const b of ed.check.blocks) {
    if (b.list !== list || !b.section || b.index == null) continue;
    const uid = (ed.sent[b.section] || [])[b.index];
    const row = uid && ed.dom.lines.querySelector(`.edit-row[data-uid="${uid}"]`);
    if (!row) continue;
    row.classList.add("is-blocked");
    row.append(el("p", { class: "edit-block", text: b.problem }));
  }
  for (const w of checkWarnings(ed.check)) {
    if (!w.mine) continue;
    for (const name of new Set(w.names)) {
      for (const row of rowsNamed(name)) {
        row.classList.add("is-warned");
        row.append(el("p", { class: "edit-warn", text: w.text }));
      }
    }
  }
}

function bracketBox(b) {
  const gcs = b.game_changers || [];
  return el("div", { class: "box" },
    el("h3", { text: "Commander bracket" }),
    el("p", {}, el("b", { text: "The list fits: " }), b.label,
      b.target ? ` (the target is Bracket ${b.target})` : ""),
    gcs.length ? el("p", { class: "sub" }, `Game Changers (${gcs.length}): `, gcs.map((g) => g.name).join(", "), ".")
      : el("p", { class: "sub", text: "No Game Changers." }),
    (b.reasons || []).map((r) => el("p", { class: "sub", text: r })));
}

function ownedPreview(o, version = "target") {
  const t = o.totals;
  const missing = o.rows.filter((r) => r.missing > 0).sort((a, b) => b.missing - a.missing || a.name.localeCompare(b.name));
  const coming = o.rows.filter((r) => r.labels && r.labels.on_the_way && r.labels.on_the_way.length).length;
  if (!o.rows.length) {
    return el("div", { class: "box" }, el("h3", { text: "Owned vs needed" }),
      el("p", { class: "sub", text: "Only basic lands so far: they aren't counted." }));
  }
  return el("div", { class: "box" },
    el("h3", { text: "Owned vs needed" }),
    el("p", {}, t.missing
      ? [status("warn", `${t.missing} missing`), ` ${plural(t.missing, "copy", "copies")} still to get` +
        (o.price_error || t.aud_missing == null ? "." : `, about ${aud(t.aud_missing)} (estimate).`)]
      : [status("good", "Covered"), " Every card is available now or on the way after allowing for other built decks."],
    coming ? ` ${plural(coming, "card")} counted as on the way.` : ""),
    missing.length ? el("details", { class: "more" }, el("summary", { text: `What's missing (${missing.length})` }),
      el("ul", { class: "sources-list" }, missing.map((r) => el("li", { text: `${r.missing} ${r.name}` +
        (r.aud_each != null ? ` (about A$${r.aud_each.toFixed(2)} each)` : "") })))) : null,
    o.price_error ? el("p", { class: "price-note", text: `No AUD estimates: ${o.price_error}` })
      : el("p", { class: "price-note", text: `A$ are estimates: Scryfall's US prices of ${o.price_date} × 1 USD = ${o.rate} AUD (ECB rate of ${o.rate_date}).` }));
}


// ------------------------------------------------------------------- saving

/** Save (the bar, Ctrl/Cmd+S): check the draft, then save at once and stay in the editor, unless something
 * blocks it, the deck changed since, or the check failed: the review sheet says so then. viewAfter: open
 * the deck once it's saved ("Save & view deck"). */
async function saveNow({ viewAfter = false } = {}) {
  const ed = editor;
  if (!ed || ed.readOnly || ed.saving || ed.promoting || ed.leaving || ed.profile !== state.profile?.id || ed.consideringUnavailable || ed.promotionUnavailable) return;
  const current = editorWriteOwner(ed);
  ed.viewAfter = viewAfter;
  const button = ed.dom.barParts && ed.dom.barParts.save;
  // Saving until the save itself has answered: a second Ctrl+S meanwhile would send the old sha again.
  ed.saving = true;
  refreshKeyboardHints();
  if (button) busy(button, ed.mode === "new" ? "Creating…" : "Saving…");
  try {
    let answer = null;
    // A check replaced by a newer one (a quantity typed while it ran) isn't a failed check: check again.
    for (let tries = 0; tries < 3 && editor === ed; tries += 1) {
      const info = {};
      answer = await runCheck(ed, info);
      if (answer || !info.superseded) break;
    }
    if (!current()) return;
    if (button) unbusy(button);
    const title = ed.mode === "new" ? titleProblem() : null;
    if (!answer || answer.file_changed || answer.blocks.length || title || editorPromotionReviewNeeded(ed)) {
      reviewSave(answer);
      return;
    }
    const c = answer.changes;
    if (ed.mode === "edit" && !c.decklist && !c.categories && !c.considering && !c.fields.length && !(c.prose || []).length && !c.marker) {
      if (viewAfter) { ed.leaving = !isDirty(); location.hash = deckHref(ed.id, ed.version); return; }
      toast(`Nothing to save: the ${listName(ed.version, true)} and the details are as saved.`);
      return;
    }
    await doSave(null, button, { viewAfter });
  } finally {
    ed.saving = false;
    if (button && editor === ed && button.dataset.busy) unbusy(button);
    if (editor === ed) refreshKeyboardHints();
  }
}

/** The review sheet: what changes, the blocks, the warnings and what saving does. answer: a check's that
 * saveNow already has (else it checks again). */
async function reviewSave(answer = undefined) {
  const ed = editor;
  if (ed.readOnly) return;            // someone else's deck: tried and tested, never saved here
  const sheet = openSheet(ed.mode === "new" ? "Create this deck?" : `Save ${ed.title}?`, { wide: true });
  const current = editorWriteOwner(ed, sheet);
  sheet.body.append(loadingBox("Checking the deck…"));
  sheetActions(sheet, [{ text: "Keep editing", onclick: () => sheet.close() }]);
  if (answer === undefined) answer = await runCheck(ed);
  if (!current()) return;
  if (!answer && ed.gone) {
    // The deck was deleted since it was loaded: nothing to save into.
    showConflict(sheet, { message: ed.gone.message, data: { conflict: ed.gone.conflict } });
    return;
  }
  if (!answer) {
    if (ed.checkError && renamedEditorConflict(sheet, ed.checkError)) return;
    clear(sheet.body).append(el("div", { class: "box box-crit" }, el("p", {
      text: `The deck couldn't be checked, so it can't be saved yet: ${ed.checkError ? ed.checkError.message : "try again."}` })));
    sheetActions(sheet, [{ text: "Try again", kind: "primary", onclick: () => { sheet.close(); reviewSave(); } },
      { text: "Keep editing", onclick: () => sheet.close() }]);
    return;
  }
  drawReview(sheet, answer);
}

/** A new deck's header fields as the review lists them ([label, words]): what creating it writes. */
function newDeckFacts() {
  const f = editor.fields;
  const home = !editor.space || editor.space === HOME_SPACE;
  const kitShown = f.status === "built" && home && mayDo("see_accessories");
  return [["Title", norm("title", f.title) || "(none yet)"], ["Format", KIND_WORDS[f.kind]],
    home ? null : ["Whose deck", spaceName(editor.space)],
    home ? ["Played by", fieldValueWords("player", f.player)] : null, ["Status", STATUS_WORDS[f.status]],
    ["Archetype", norm("archetype", f.archetype) || "not set"],
    kitShown ? ["Sleeves", kitName("sleeves", f.sleeves) || "not set"] : null,
    kitShown ? ["Deck box", kitName("deck_box", f.deck_box) || "not set"] : null,
    f.kind === "commander" ? ["Target bracket", fieldValueWords("target_bracket", f.target_bracket)] : null]
    .filter(Boolean);
}

function drawReview(sheet, a) {
  const ed = editor;
  const body = clear(sheet.body);
  const who = state.profile.name;
  const isNew = ed.mode === "new";
  const blocks = [...a.blocks];
  if (isNew) {
    const problem = titleProblem();
    if (problem) blocks.unshift({ field: "title", problem });
  }
  // What changes: the cards, then the header.
  const reference = ed.starting ? ed.view.lists.target : ed.base.lists;
  const cardChanges = listChanges(reference, ed.lists);
  // A Sleeves or Deck box line a person-space profile can't see isn't named (taking a deck apart clears it).
  const fieldChanges = isNew ? [] : Object.entries(changedFields())
    .filter(([k]) => mayDo("see_accessories") || !KIT_FIELDS.includes(k)).map(([k, v]) => fieldChangeWords(k, v));
  const proseChanges = isNew ? [] : (a.changes.prose || []);
  const marker = !isNew && !!a.changes.marker;
  // The lines' own categories (E2-S24): a change of them alone is a save, though not a decklist change.
  const categoryEdits = isNew || ed.starting ? [] : categoryChanges(reference, ed.lists);
  // A draft with blocks isn't applied, so its changes can read as none: show the blocks then.
  const nothing = !isNew && !a.blocks.length && !a.changes.decklist && !a.changes.categories && !a.changes.fields.length
    && !proseChanges.length && !marker && !a.changes.considering;
  if (a.file_changed) {
    body.append(el("div", { class: "box box-warn" },
      el("h3", { text: "This deck changed after you opened it" }),
      el("p", { text: "A save from here would be refused. Load the latest version and your changes are put back on top of it; then save again. Or discard your changes and take the latest version as it is." })));
    sheetActions(sheet, [
      { text: "Load the latest and re-apply my changes", kind: "primary", onclick: (e) => reapplyLatest(sheet, null, e.currentTarget) },
      { text: "Discard my changes", kind: "discard", onclick: () => askDiscardChanges(sheet) },
      { text: "Keep editing", onclick: () => sheet.close() }]);
    return;
  }
  if (nothing) {
    body.append(el("p", {}, status("plain", "Nothing to save"),
      ` The ${listName(ed.version, true)} and the details are the same as in the saved deck.`));
    sheetActions(sheet, [{ text: "Keep editing", kind: "primary", onclick: () => sheet.close() }]);
    return;
  }
  const title = isNew ? norm("title", ed.fields.title) : null;
  if (isNew) {
    body.append(el("dl", { class: "review-facts" },
      newDeckFacts().map(([k, v]) => el("div", {}, el("dt", { text: k }), el("dd", { text: v })))));
  }
  let counts = a.counts && a.counts[isNew ? "target" : ed.version];
  if (isNew && !ed.from) {
    const lines = Object.entries(ed.lists).flatMap(([section, list]) => list.map((l) => [section, l]));
    if (!lines.length) counts = null;         // "No cards yet" says it
    body.append(lines.length
      ? el("details", { class: "more" }, el("summary", { text: `The list (${plural(lines.length, "line")})` }),
        el("ul", { class: "review-list" }, lines.map(([section, l]) => el("li", { class: "review-added" },
          el("span", { class: "review-mark", "aria-hidden": "true", text: "+" }),
          `${l.qty} ${l.name}` + (l.set ? ` (${printingText(l)})` : "") + (section !== "Deck" ? ` (${sectionWords(section)})` : "")))))
      : el("p", { text: "No cards yet: you can add them after it's created." }));
  } else if (cardChanges.length || ed.starting) {
    const target = ed.starting ? sectionCount(ed.view.lists.target, Object.keys(ed.view.lists.target)) : 0;
    const heading = ed.starting ? `Starts the ${listName("owned", true)} as a copy of the ${listName("target", true)} (${plural(target, "card")})` +
      (cardChanges.length ? ", with these changes:" : ".")
      : isNew ? `Changes from ${ed.view.title}:` : `Changes to the ${listName(ed.version, true)}:`;
    body.append(el("h3", { text: heading }));
    const bySection = new Map();
    for (const c of cardChanges) {
      if (!bySection.has(c.section)) bySection.set(c.section, []);
      bySection.get(c.section).push(c);
    }
    for (const [section, list] of bySection) {
      add(body, [bySection.size > 1 || section !== "Deck" ? el("h4", { class: "review-section", text: sectionTitle(section) }) : null,
        el("ul", { class: "review-list" }, list.map((c) => el("li", { class: `review-${changeKind(c)}` },
          el("span", { class: "review-mark", "aria-hidden": "true", text: { added: "+", removed: "−", changed: "~" }[changeKind(c)] }),
          changeWords(c))))]);
    }
  } else if (isNew) {
    body.append(el("p", { text: `The list is ${ed.view.title}'s, unchanged.` }));
  }
  if (categoryEdits.length) {
    body.append(el("h3", { text: "Changes to your categories:" }),
      el("ul", { class: "review-list" }, categoryEdits.map((c) => el("li", { class: "review-changed" },
        el("span", { class: "review-mark", "aria-hidden": "true", text: "~" }), categoryChangeWords(c)))));
  }
  editorConsideringReview(body, a);
  const promotionAck = editorPromotionReview(body, a, sheet);
  if (proseChanges.length || marker) {
    body.append(el("h3", { text: "Changes to the write-up:" }),
      el("ul", { class: "review-list" },
        proseChanges.map((key) => el("li", { class: "review-changed" }, el("span", { class: "review-mark", "aria-hidden": "true", text: "~" }),
          key === "notes" ? "Notes" : "Substitutes")),
        marker ? el("li", { class: "review-removed" }, el("span", { class: "review-mark", "aria-hidden": "true", text: "−" }),
          "The “Decklist changed” line: the write-up is current") : null));
  }
  if (fieldChanges.length) {
    body.append(el("h3", { text: "Changes to the details:" }),
      el("ul", { class: "review-list" }, fieldChanges.map((t) => el("li", { class: "review-changed" },
        el("span", { class: "review-mark", "aria-hidden": "true", text: "~" }), t))));
  }
  if (counts) {
    const kind = currentKind();          // counts.main is the Deck, plus the commander of a Commander deck
    body.append(el("p", { class: "sub", text: `After saving: ${plural(counts.main, "card")}` +
      (kind === "commander" ? " with the commander" : " in the deck") +
      (counts.sideboard ? `, ${counts.sideboard} in the sideboard` : "") + "." }));
  }
  if (blocks.length) {
    body.append(blocksBox(blocks, () => {
      ed.confirmEmpty = true;
      sheet.close();
      reviewSave();
    }));
  }
  if (a.warnings.length) {
    const list = warningList(a, () => sheet.close());
    body.append(el("div", { class: "box box-warn" },
      el("h3", { text: `Worth a look first (${a.warnings.length})` }),
      el("p", { class: "sub", text: "These don't stop the save." }),
      a.warnings.length > 4 ? el("details", { class: "more" }, el("summary", { text: "Show them" }), list) : list));
  }
  const slug = isNew ? slugOf(title || "") : null;
  const space = isNew ? (editor.space || HOME_SPACE) : HOME_SPACE;
  const newId = slug ? (space !== HOME_SPACE ? `${space}/` : "") + `${ed.fields.kind}/${slug}` : null;
  body.append(el("div", { class: "what-saving-does" },
    el("h3", { text: "Saving" }),
    el("ul", { class: "sources-list" },
      el("li", { text: !isNew ? `Saves ${ed.title} in Deck Lab. Only the parts Deck Lab looks after change; the write-up around them stays as it is.`
        : newId ? `Creates the deck ${newId} in Deck Lab, with the list, the details and empty Substitutes and Notes sections.`
          : "Creates the deck in Deck Lab, named after the title, with the list, the details and empty Substitutes and Notes sections." }),
      !isNew && a.changes.decklist && !marker ? el("li", { text: "Adds a line saying the list changed in Deck Lab today, so the write-up (the Notes tab) can be brought up to date later." }) : null,
      isNew || a.changes.decklist || a.changes.fields.length ? el("li", { text: isNew ? "Works out the deck's owned-vs-needed table from the list, with today's prices."
        : `Works out the deck's owned-vs-needed table again, from the ${listName("target", true)}, with today's prices.` }) : null,
      el("li", { text: `The change is kept in the deck's history, under your name (${who}).` }))));
  sheetActions(sheet, [
    { text: isNew ? "Create" : "Save", kind: "primary", disabled: blocks.length > 0 || promotionAck, value: "save",
      onclick: (e) => doSave(sheet, e.currentTarget, { viewAfter: !!ed.viewAfter }) },
    { text: "Keep editing", onclick: () => sheet.close() }]);
}

/** Save the draft. sheet: the review sheet it was asked from, or null (saved straight from the bar). After a
 * save the editor reloads the saved deck in place with a toast, or with viewAfter opens the deck page. */
async function doSave(sheet, button, { viewAfter = false } = {}) {
  const ed = editor;
  const current = editorWriteOwner(ed, sheet);
  if (!current() || ed.consideringUnavailable || ed.promotionUnavailable || ed.promoting || editorPromotionReviewNeeded(ed)) return;
  const retest = typeof editorRetestIntent === "function" ? editorRetestIntent(ed) : null;
  if (button) busy(button, "Saving...");
  let answer;
  try {
    answer = ed.mode === "new"
      ? await apiWrite("/api/decks", { title: norm("title", ed.fields.title), ...draftBody() })
      : await apiWrite("/api/deck/save", draftBody());
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    if (button) unbusy(button);
    if (!current()) return;
    if (!sheet) {
      // Saved from the bar: the review sheet says what went wrong.
      sheet = openSheet(ed.mode === "new" ? "Create this deck?" : `Save ${ed.title}?`, { wide: true });
    }
    if (e.status === 409 && ed.mode === "edit") return showConflict(sheet, e);
    const blocks = e.data && e.data.blocks;
    clear(sheet.body).append(el("div", { class: "box box-crit" },
      el("h3", { text: ed.mode === "new" && e.status === 409 ? "That title is taken" : "It wasn't saved" }),
      el("p", { text: e.message + (e.status && !blocks && e.status !== 409 ? ` (error ${e.status})` : "") }),
      blocks ? el("ul", {}, blocks.map((b) => el("li", { text: b.problem }))) : null));
    sheetActions(sheet, [
      e.status >= 500 || e.status === 0 ? { text: "Try again", kind: "primary", onclick: () => { sheet.close(); saveNow({ viewAfter }); } } : null,
      { text: "Keep editing", kind: e.status >= 500 || e.status === 0 ? "" : "primary", onclick: () => {
        sheet.close();
        if (ed.mode === "new" && e.status === 409) { const t = document.getElementById("f-title"); if (t) t.focus(); }
      } }]);
    if (blocks) { ed.check = { warnings: [], ...(ed.check || {}), blocks }; drawCheck(); markRows(); drawBar(); }
    return;
  }
  // A stale save response must not start a run or replace another page/person's editor.
  if (!current() || (retest && !editorForgeSummaryCurrent(retest.context))) {
    ed.confirmedSave = answer;
    if (button) unbusy(button);
    return;
  }
  let retestTask = null;
  if (retest) {
    answer.after_save_test = { kind: "info", text: "The deck was saved. Requesting its field re-test..." };
    retestTask = queueEditorRetest(retest, answer);
  }
  if (button) unbusy(button);
  state.library = null;               // the library's counts changed
  const removed = removeDraft(ed);
  if (removed && viewAfter) {
    ed.leaving = true;
    toast("");                          // an older note would cover the box about the save
    const hash = deckHref(answer.id, ed.mode === "new" ? "target" : ed.version);
    state.saved = { hash, answer, version: ed.version, mode: ed.mode, profile: ed.profile };
    state.scroll.delete(hash);          // open the deck at the top, where the box about the save is
    if (sheet) sheet.close();
    location.hash = hash;
    if (retestTask) observeEditorRetest(retestTask, answer, { saved: state.saved });
    return;
  }
  // Stay in the editor, on the saved deck. When this browser couldn't remove the old draft, continue from
  // the save's exact answer without replaying the old draft or saving again; cleanup is retried before any
  // later draft or navigation.
  const oldKey = removed ? null : ed.pendingDraftKey || draftKey(ed);
  if (sheet) sheet.close();
  const version = ed.mode === "new" ? "target" : ed.version;
  const created = ed.mode === "new";
  const keep = { side: ed.side, look: ed.look, tab: ed.tab, detailsOpen: ed.detailsOpen };
  history.replaceState(history.state, "", editHref(answer.id, version));
  clearTimeout(ed.checkTimer);
  clearTimeout(ed.draftTimer);
  ed.leaving = true;
  startEditor({ mode: "edit", view: answer.deck, version, restoreDraft: false, pendingDraftKey: oldKey });
  const now = editor;
  Object.assign(now, keep);
  now.afterSaveTest = answer.after_save_test || null;
  if (answer.stale_tables && answer.stale_tables.length) now.notice = { kind: "saved", stale: answer.stale_tables };
  drawEditor();
  if (retestTask) observeEditorRetest(retestTask, answer, { ed: now });
  if (!removed) {
    toast("The deck was saved in Deck Lab. This browser couldn't remove its old draft; the saved version is open below.");
    return;
  }
  const words = created ? `${answer.title} is created.` : answer.changed === false ? "Nothing needed saving." : `Saved ${answer.title}.`;
  showToast(words, { undoText: "View deck", undo: () => { location.hash = deckHref(answer.id, version); } });
}

function showConflict(sheet, error) {
  if (renamedEditorConflict(sheet, error)) return;
  const c = (error.data && error.data.conflict) || {};
  if (c.reason === "deleted") {
    // Nothing to load and re-apply onto: the deck was deleted.
    // The check's 409 (or a save's) leads here too; the editor's banner says the same.
    const ed = editor;
    if (ed && !ed.gone) {
      ed.gone = { message: error.message, conflict: c };
      drawBanners();
    }
    sheet.heading.textContent = GONE_TITLE;
    clear(sheet.body).append(
      el("div", { class: "box box-warn" }, el("p", { text: error.message.replace(/ Your changes weren't saved\.$/, "") })),
      el("p", { text: `Nothing was saved. ${GONE_WORDS}` }));
    sheetActions(sheet, [...goneActions(sheet), { text: "Keep editing", onclick: () => sheet.close() }]);
    return;
  }
  sheet.heading.textContent = "The deck changed after you opened it";
  clear(sheet.body).append(
    el("div", { class: "box box-warn" }, el("p", { text: error.message.replace(/ Your changes weren't saved\.$/, "") })),
    el("p", { text: "Nothing was saved. Your changes are still in this open editor." }),
    el("p", { text: "Load the latest version and your changes are put back on top of it (what you added, took out or changed, card by card, and the details you changed). You'll see the result before saving again." }));
  sheetActions(sheet, [
    { text: "Load the latest and re-apply my changes", kind: "primary", onclick: (e) => reapplyLatest(sheet, error, e.currentTarget) },
    { text: "Discard my changes", kind: "discard", onclick: () => askDiscardChanges(sheet) }]);
}

async function reapplyLatest(sheet, error, button) {
  const ed = editor;
  const current = editorWriteOwner(ed, sheet);
  if (!current()) return;
  if (button) busy(button, "Loading the latest...");
  let view;
  try {
    view = await api(`/api/deck/edit?id=${encodeURIComponent(ed.id)}`);
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    if (button) unbusy(button);
    if (!current()) return;
    toast(`The latest version couldn't be loaded: ${e.message}`);
    return;
  }
  if (!current()) return;
  if (view.id !== ed.id) {
    if (!sheet) sheet = openDeckRetirementSheet({ title: "This deck has been renamed" });
    renamedEditorConflict(sheet, new ApiError(409, "This deck was renamed while the latest version was loading.",
      { canonical_id: view.id, conflict: { reason: "renamed" } }));
    return;
  }
  if (!view.editable) {
    if (sheet) sheet.close();
    toast(view.why_not || "This deck can't be edited any more.");
    return;
  }
  const mine = { lists: ed.lists, fields: ed.fields, starting: ed.starting,
    prose: ed.prose, markCurrent: ed.markCurrent, ...editorConsideringSnapshot(ed) };
  const notes = rebase(ed, view, mine, ed.base);
  ed.notice = { kind: "reapplied", why: error ? error.message : null, notes };
  ed.check = null;
  if (sheet) sheet.close();
  syncSections();
  drawEditor();
  changed({ list: false });
  saveDraft(ed);
  window.scrollTo(0, 0);
  $("#main").focus({ preventScroll: true });
}

/** Drop the changes made here and load the deck as it's saved now. sheet: the one asking, or null. */
function discardChanges(sheet) {
  const ed = editor;
  if (!removeDraft(ed)) return;
  ed.leaving = true;
  if (sheet) sheet.close();
  toast("Your changes were discarded: this is the deck as it is now.");
  route();
}
