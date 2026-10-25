/* Deck Lab's editor: drawing the editor screen (Milestone 4; the layout of UI-REVIEW.md WP11).

Loaded after editor.js and before editor-details.js, editor-lines.js, editor-cards.js, editor-save.js and
editor-deckpage.js (then matchups.js and the page's other scripts, core.js to app.js). It holds the
editor's page and its head, the banners (a draft brought back, changes re-applied, a deck deleted or
changed since, a save that left other decks' tables out of date), the main tabs (Cards and Notes: the
list's place, the look switch, and the write-up), the side panel's tabs (Add, Stats and Checks),
changed() and the bar at the bottom with its split Save. Deck details are editor-details.js's and the
list's rows editor-lines.js's. It uses editor.js's constants, `editor`, lines, fields, drafts, history
and sheets, editor-details.js's Deck details, editor-lines.js's list, editor-cards.js's Add panel, search
sheet and printing sheet, and editor-save.js's checks, saving and discarding.

Layout (editor.css): from 1,000 px (an iPad in landscape) Deck details and the list are one column and the
side panel a sticky column beside them; below that Deck details, the panel and the list come one after the
other. The Notes tab has the whole width. From 1,400 px with a mouse the card pointed at shows in the peek
column (deck.js peekLayout). On a phone (quickEditing) the editor is the Quick edit: compact rows with
steppers, "Add cards" opening a search sheet with Paste a list, a line's ⋯ (printing, move, remove),
the status, folded Deck details, Notes and Save. Pictures and the side panel stay on larger screens.
A new deck on a phone is the Quick edit with its title and format.
*/
"use strict";

const DECK_SIZE = { casual: 60, commander: 100 };
const FILE_FIELDS = { status: "Status", player: "Played by" };     // field_text keys for "the deck says"
const SIDE_TABS = [["add", "Add"], ["stats", "Stats"], ["checks", "Checks"]];
const CURVE_TOP = 7;            // the curve's last column: 7 or more


// ----------------------------------------------------------------- drawing

function drawEditor() {
  const ed = editor;
  const main = $("#main");
  const focus = document.activeElement && main.contains(document.activeElement)
    ? document.activeElement.dataset.focus : null;
  clear(main);
  ed.dom = {};
  document.body.classList.add("has-edit-bar");      // the toast goes above the bar (components.css)
  document.body.classList.toggle("is-quick-edit", !!ed.quick);
  setTitle(ed.mode === "edit" ? `Edit ${ed.title}` : ed.from ? "Save as a new deck" : "New deck");
  const back = ed.mode === "edit" ? [deckHref(ed.id, ed.version), ed.title]
    : ed.from ? [deckHref(ed.from), ed.view.title] : [state.libraryHash || "#/library", routeFor("library").label];
  const listOpen = !noOwnedList();
  ed.dom.banners = el("div", { class: "edit-banners" });
  ed.dom.lines = el("div", { class: "edit-lines" });
  ed.dom.check = el("section", { class: "edit-check", id: "edit-check", "aria-labelledby": "h-check", tabindex: "-1" });
  ed.dom.bar = el("div", { class: "edit-bar" });
  const side = ed.quick || !listOpen ? null : sidePanel();
  // Deck details, the side panel and the list share one grid (editor.css): the side panel starts level with
  // Deck details on a wide screen.
  const work = el("div", { class: "edit-work" + (side ? "" : " edit-work-single") },
    detailsPart(), side, el("div", { class: "edit-main" }, mainTabs(), ed.dom.mainBody = el("div", { class: "edit-main-body" })));
  // deck.js: on a wide screen with a mouse, the card last pointed at shows beside the editor.
  add(main, [ed.dom.page = el("div", { class: "edit-page" + (ed.quick ? " is-quick" : "") },
    peekLayout(`edit:${ed.mode}:${ed.id || ed.from || ""}:${ed.version}`, firstCard(ed.lists), [
      crumb(back[0], back[1]),
      editorHead(),
      ed.dom.banners,
      work,
      side || !listOpen ? null : ed.dom.check,
      ed.dom.bar]))]);
  drawMain();
  drawBanners();
  drawCheck();
  drawBar();
  if (focus) {
    const again = main.querySelector(`[data-focus="${CSS.escape(focus)}"]`);
    if (again) again.focus({ preventScroll: true });
  }
}

/** A new deck's "Whose deck" choice, when the visitor may add decks in more than one space (an admin);
 * null otherwise. Changing it sets Played by to suit the space (none in a person's space). */
function spaceField() {
  const ed = editor;
  const spaces = [...new Set(createTargets().map((t) => t.space))];
  if (spaces.length < 2) return null;
  const group = el("div", { class: "segmented", role: "group", "aria-labelledby": "f-space" });
  for (const space of spaces) {
    group.append(el("button", { type: "button", "aria-pressed": String(ed.space === space), "data-space": space,
      text: space === HOME_SPACE ? "Home" : spaceName(space),
      onclick: () => {
        if (ed.space === space) return;
        ed.space = space;
        ed.fields.player = newDeckPlayer(space);
        drawDetails();
        drawTitleHint();
        changed({ list: false });
      } }));
  }
  return el("div", { class: "field field-wide field-space" }, el("span", { id: "f-space", text: "Whose deck" }), group);
}

function editorHead() {
  const ed = editor;
  const head = el("header", { class: "deck-head edit-head" });
  if (ed.mode === "edit") {
    head.append(el("div", { class: "edit-title-row" },
      el("h1", { text: ed.title }),
      ed.readOnly ? status("info", "Trying a change") : null),
    el("nav", { class: "version-pick", "aria-label": "Which list to edit" },
      el("div", { class: "segmented" }, ["target", "owned"].map((v) => el("a", {
        href: editHref(ed.id, v), "aria-current": v === ed.version ? "page" : null },
      listName(v), v === "owned" && ed.view.lists.owned == null ? el("span", { class: "none-yet", text: " (none yet)" }) : null)))));
    if (ed.readOnly) {
      head.append(el("p", { class: "sub edit-read-only", text: ed.space === HOME_SPACE
        ? "Only the people this deck belongs to can save it. Try changes and test them; nothing is saved."
        : `Only ${spaceName(ed.space)} can save this deck. Try changes and test them; nothing is saved.` }));
    }
  } else {
    add(head, [el("h1", { text: ed.from ? "Save as a new deck" : "New deck" }),
      ed.from ? el("p", { class: "deck-format", text: `Starts from ${ed.view.title}, which stays as it is.` }) : null]);
  }
  return head;
}

function drawBanners() {
  const ed = editor;
  const host = ed.dom.banners;
  if (!host) return;
  clear(host);
  if (ed.draftRemoveFailed) {
    host.append(el("div", { class: "box box-warn banner", role: "alert" },
      el("h2", { text: ed.pendingDraftKey ? "The deck was saved, but its old draft couldn't be removed"
        : "The stored draft couldn't be removed" }),
      el("p", { text: "The browser's storage is unavailable. Keep this tab open: leaving an old draft could bring back changes already saved or discarded." }),
      el("button", { type: "button", class: "btn", text: "Try clearing the old draft",
        onclick: () => { if (saveDraft(ed)) toast("Draft storage is available again; your current changes are kept on this device."); } })));
  }
  if (ed.draftFailed) {
    host.append(el("div", { class: "box box-warn banner", role: "alert" },
      el("h2", { text: "Your changes couldn't be kept on this device" }),
      el("p", { text: "The browser's storage is full or unavailable. Your changes are still in this open editor. Save the deck before closing or reloading this tab." })));
  }
  const n = ed.notice;
  const notes = (list) => (list && list.length ? el("ul", {}, list.map((t) => el("li", { text: t }))) : null);
  if (n && (n.kind === "draft" || n.kind === "draft-changed")) {
    host.append(el("div", { class: "box box-info banner", role: "status" },
      el("h2", { text: `Unsaved changes from ${timeWords(n.saved)}` }),
      n.kind === "draft-changed" ? el("p", { text: "The deck changed since then, so they've been put back on top of the latest version: check them before saving." }) : null,
      notes(n.notes),
      el("div", { class: "actions" }, el("button", { type: "button", class: "btn btn-discard", text: "Discard them",
        onclick: discardDraft }))));
  }
  if (n && n.kind === "reapplied") {
    host.append(el("div", { class: "box box-warn banner", role: "status" },
      el("h2", { text: "Your changes are back, on top of the latest version" }),
      n.why ? el("p", { text: n.why.replace(/ Your changes weren't saved\.$/, "") }) : null,
      el("p", { text: "Check the list and the details, then save again." }),
      notes(n.notes)));
  }
  if (n && n.kind === "saved" && n.stale && n.stale.length) {
    // A save in place: other decks' tables it left out of date, with "Update their tables".
    const box = el("section", { class: "box box-stale banner saved-stale" },
      el("button", { type: "button", class: "btn btn-quiet sheet-close", "aria-label": "Close this note", text: "×",
        onclick: () => { ed.notice = null; box.remove(); } }),
      staleTablesPart(n.stale));
    host.append(box);
  }
  if (ed.gone) {
    // The deck was deleted since it was loaded: nothing here can be saved into it.
    host.append(el("div", { class: "box box-warn banner", role: "alert" },
      el("h2", { text: GONE_TITLE }),
      el("p", { text: ed.gone.message.replace(/ Your changes weren't saved\.$/, "") }),
      el("p", { text: GONE_WORDS }),
      el("div", { class: "actions" }, goneActions().map((a) => el("button", { type: "button",
        class: `btn${a.kind ? ` btn-${a.kind}` : ""}`, text: a.text, onclick: a.onclick })))));
  } else if (ed.check && ed.check.file_changed) {
    host.append(el("div", { class: "box box-warn banner", role: "alert" },
      el("h2", { text: "This deck changed after you opened it" }),
      el("p", { text: "Someone saved it since this page loaded it, so a save from here would be refused. Load the latest version and your changes are put back on top of it, or discard your changes and take the latest version as it is." }),
      el("div", { class: "actions" },
        el("button", { type: "button", class: "btn btn-primary", text: "Load the latest and re-apply my changes",
          onclick: (e) => reapplyLatest(null, null, e.currentTarget) }),
        el("button", { type: "button", class: "btn btn-discard", text: "Discard my changes", onclick: () => askDiscardChanges(null) }))));
  }
}

/** "Discard my changes" (the banner, the review, a save's 409) asks first; sheet: the one it's in, or null. */
async function askDiscardChanges(sheet) {
  const ed = editor;
  const choice = await ask("Discard your changes?", [
    "The editor loads the deck as it is now, and the changes you made here are gone. This can't be undone."],
  [{ value: "discard", text: "Discard my changes", kind: "danger" }, { value: "keep", text: "Keep them", kind: "primary" }]);
  if (choice === "discard" && editor === ed) discardChanges(sheet);
}

/** The heading for a deck deleted since it was loaded (conflict.reason "deleted"), and where the changes
 * are: decks can't be renamed, so there's nowhere to save them. */
const GONE_TITLE = "This deck is gone";
const GONE_WORDS = "Your changes are still in this editor, but they can't be saved into this deck any more.";

/** What can be done about a deck that was deleted: discard the changes (asking first) and go to the
 * library. sheet: the sheet showing them, or null (the banner). */
function goneActions(sheet = null) {
  const leave = (hash) => {
    if (editor) editor.leaving = true;
    if (sheet) sheet.close();
    location.hash = hash;
  };
  return [
    { text: "Discard my changes", kind: "discard", onclick: async () => {
      const ed = editor;
      const choice = await ask("Discard your changes?", [
        "They can't be saved into this deck any more. Discarding them takes them off this device too, and the editor closes. This can't be undone."],
      [{ value: "discard", text: "Discard my changes", kind: "danger" }, { value: "keep", text: "Keep them", kind: "primary" }]);
      if (choice !== "discard" || editor !== ed) return;
      if (!removeDraft(ed)) return;
      leave(state.libraryHash || "#/library");
    } }];
}

/** A check's answer for a deck that was deleted since it was loaded: {message, conflict}, else null.
 * The server answers 409 with the save's "conflict" (reason "deleted"); an older one answered 404. */
function goneFrom(error) {
  if (!editor || editor.mode !== "edit" || !(error instanceof ApiError)) return null;
  const c = error.data && error.data.conflict;
  if (error.status === 409 && c && c.reason === "deleted") return { message: error.message, conflict: c };
  if (error.status === 404) {
    return { message: `${editor.title} isn't there any more: it was deleted since you opened it. (${error.message}.)`,
      conflict: { reason: "deleted" } };
  }
  return null;
}

async function discardDraft() {
  const ed = editor;
  const choice = await ask("Discard your unsaved changes?", [
    "The editor goes back to the deck as it's saved now. This can't be undone."],
  [{ value: "discard", text: "Discard them", kind: "danger" }, { value: "keep", text: "Keep them", kind: "primary" }]);
  if (choice !== "discard" || editor !== ed) return;
  if (!removeDraft(ed)) return;
  ed.leaving = true;
  route();
}

// The main tabs: Cards and Notes ------------------------------------------------------

function mainTabs() {
  const ed = editor;
  const notes = ed.mode === "edit";
  if (!notes) ed.tab = "cards";
  const tab = (key, label) => el("button", { type: "button", role: "tab", id: `edit-tab-${key}`,
    "aria-selected": String(ed.tab === key), "aria-controls": "edit-main-panel", "data-focus": `tab:${key}`,
    tabindex: ed.tab === key ? "0" : "-1",
    onclick: () => { if (ed.tab !== key) { ed.tab = key; drawMain(); } } }, label);
  ed.dom.look = el("div", { class: "segmented edit-look", role: "group", "aria-label": "Show the list as" });
  const lookOffered = !ed.quick && !noOwnedList();
  // A new deck's Cards heading needs no tab bar.
  return el("div", { class: "edit-main-head" },
    notes ? el("div", { class: "tabs edit-tabs", role: "tablist", "aria-label": "Edit", onkeydown: tabArrows },
      tab("cards", "Cards"), tab("notes", "Notes"))
      : el("h2", { class: ed.quick ? "sr-only" : "edit-cards-title", text: ed.mode === "edit" ? listName(ed.version) : "Cards" }),
    lookOffered ? ed.dom.look : null);
}

/** A tablist's keys (the tabs pattern): Left and Right (wrapping), Home and End pick the tab and focus it. */
function tabArrows(e) {
  const tabs = [...e.currentTarget.querySelectorAll("[role=tab]")];
  const at = tabs.indexOf(document.activeElement);
  if (at < 0) return;
  const to = { ArrowRight: at + 1, ArrowLeft: at - 1, Home: 0, End: tabs.length - 1 }[e.key];
  if (to === undefined) return;
  e.preventDefault();
  const tab = tabs[(to + tabs.length) % tabs.length];
  tab.click();
  const again = document.getElementById(tab.id);
  if (again) again.focus();
}

function drawLookSwitch() {
  const ed = editor;
  if (!ed.dom.look) return;
  clear(ed.dom.look).append(...[["list", "List"], ["visual", "Pictures"]].map(([key, label]) =>
    el("button", { type: "button", "aria-pressed": String(ed.look === key), "data-focus": `look:${key}`,
      onclick: () => {
        if (ed.look === key) return;
        ed.look = key;
        local.set("editLook", key);
        drawLines();
        drawLookSwitch();
        showRowAvailability(currentAvailability());
      } }, label)));
  ed.dom.look.hidden = ed.tab !== "cards";
}

/** The main column's body: the list, or the write-up. */
function drawMain() {
  const ed = editor;
  const host = ed.dom.mainBody;
  if (!host) return;
  document.querySelectorAll(".edit-tabs [role=tab]").forEach((t) => {
    t.setAttribute("aria-selected", String(t.id === `edit-tab-${ed.tab}`));
    t.setAttribute("tabindex", t.id === `edit-tab-${ed.tab}` ? "0" : "-1");
  });
  if (ed.dom.page) ed.dom.page.classList.toggle("is-notes", ed.tab === "notes");
  clear(host).setAttribute("id", "edit-main-panel");
  if (document.getElementById(`edit-tab-${ed.tab}`)) {
    host.setAttribute("role", "tabpanel");
    host.setAttribute("aria-labelledby", `edit-tab-${ed.tab}`);
  }
  if (ed.tab === "notes") {
    host.append(notesPart());
    if (ed.dom.look) ed.dom.look.hidden = true;
    return;
  }
  host.append(ed.dom.lines);
  drawLookSwitch();
  drawLines();
  showRowAvailability(currentAvailability());
}

// The write-up ----------------------------------------------------------------------

/** The Notes tab: the deck's write-up (its Notes and Substitutes sections, which Deck Lab doesn't write) in
 * text boxes, and "Mark write-up as current" while the deck says its list changed since. Saved with Save. */
function notesPart() {
  const ed = editor;
  const changedOn = ed.view && ed.view.changed_on;
  const box = (key, label, rows) => {
    const id = `prose-${key}`;
    const area = el("textarea", { id, class: "prose-area", rows, spellcheck: "true", "data-focus": `prose:${key}`,
      value: (ed.prose && ed.prose[key]) || "" });
    area.value = (ed.prose && ed.prose[key]) || "";
    area.title = "Markdown: ### starts a heading";
    // The box grows with what's in it, so the write-up reads as a page rather than in a small window.
    const fit = () => {
      if (!area.style || !area.isConnected) return;
      area.style.height = "auto";
      area.style.height = `${area.scrollHeight + 2}px`;
    };
    area.addEventListener("input", () => {
      ed.prose = { ...(ed.prose || {}), [key]: area.value };
      fit();
      changed({ list: false });
    });
    if (typeof requestAnimationFrame === "function") requestAnimationFrame(fit);
    return el("label", { class: "field field-wide", for: id }, el("span", { text: label }), area);
  };
  const marker = !changedOn ? null : ed.markCurrent
    ? el("div", { class: "note note-good edit-marker" },
      el("p", { text: "The write-up will be marked as current when you save." }),
      el("button", { type: "button", class: "btn btn-quiet", text: "Undo", onclick: () => {
        ed.markCurrent = false; changed({ list: false }); drawMain(); } }))
    : el("div", { class: "note note-warn edit-marker" },
      el("p", { text: `The list changed in Deck Lab on ${changedOn}, so the write-up may be out of date.` }),
      el("button", { type: "button", class: "btn", text: "Mark write-up as current", onclick: () => {
        ed.markCurrent = true; changed({ list: false }); drawMain(); } }));
  return el("section", { class: "edit-notes", "aria-label": "Write-up" }, marker,
    box("notes", "Notes: game plan, mulligans, sideboarding", 18),
    box("substitutes", "Substitutes: what to play until missing cards arrive", 6));
}

/** Something changed: redraw what shows it, keep the draft and the undo history, and check again soon. */
function changed({ list = true, history = true } = {}) {
  const ed = editor;
  ed.dirty = isDirty();
  if (history && ed.history) recordHistory(ed);
  if (list) {
    drawLines();
    drawKitNeeds();
  } else {
    drawKitNeeds();
  }
  drawStats();
  drawDetailsSummary();
  drawBar();
  queueDraft();
  scheduleCheck();
}

// The side panel: Add, Stats and Checks ----------------------------------------------------

function sidePanel() {
  const ed = editor;
  if (!SIDE_TABS.some(([key]) => key === ed.side)) ed.side = "add";
  ed.dom.sideTabs = el("div", { class: "tabs edit-side-tabs", role: "tablist", "aria-label": "Add, stats and checks",
    onkeydown: tabArrows });
  ed.dom.sideBody = el("div", { class: "edit-side-body", role: "tabpanel", id: "edit-side-panel" });
  ed.dom.addPart = addPart();
  ed.dom.stats = el("div", { class: "edit-stats" });
  ed.dom.check.classList.add("edit-check-side");
  // Below 1,000 px (editor.css) the panel is folded to its tabs once the deck has cards, so the list starts on
  // the first screen; the fold button (and a tab, or Add cards) opens it.
  if (ed.sideFolded === undefined) ed.sideFolded = !emptyList();
  ed.dom.sideFold = el("button", { type: "button", class: "btn btn-quiet edit-side-fold", "aria-controls": "edit-side-panel",
    onclick: () => foldSide(!ed.sideFolded) });
  drawSideTabs();
  showSide();
  ed.dom.side = el("aside", { class: "panel edit-side", "aria-label": "Add, stats and checks" },
    el("div", { class: "edit-side-head" }, ed.dom.sideTabs, ed.dom.sideFold), ed.dom.sideBody);
  foldSide(ed.sideFolded);
  return ed.dom.side;
}

/** Folds the side panel to its tabs (below 1,000 px; a wide screen always shows it), or opens it. */
function foldSide(folded) {
  const ed = editor;
  ed.sideFolded = folded;
  if (!ed.dom.side) return;
  ed.dom.side.classList.toggle("is-folded", folded);
  ed.dom.sideFold.textContent = folded ? "Show" : "Hide";
  ed.dom.sideFold.setAttribute("aria-expanded", String(!folded));
}

function drawSideTabs() {
  const ed = editor;
  if (!ed.dom.sideTabs) return;
  const focused = document.activeElement && ed.dom.sideTabs.contains(document.activeElement) ? document.activeElement.id : null;
  const a = ed.check;
  const blocks = (a ? a.blocks.length : 0) + (typedTitleProblem() ? 1 : 0);
  const warnings = a && !emptyList() ? a.warnings.length : 0;
  clear(ed.dom.sideTabs).append(...SIDE_TABS.map(([key, label]) => el("button", { type: "button", role: "tab",
    id: `edit-side-${key}`, "aria-selected": String(ed.side === key), "aria-controls": "edit-side-panel",
    tabindex: ed.side === key ? "0" : "-1", onclick: () => setSide(key) }, label,
  key === "checks" && (blocks || warnings) ? el("span", { class: `chip chip-${blocks ? "crit" : "warn"} tab-count`,
    text: String(blocks || warnings), "aria-label": blocks ? plural(blocks, "problem") : plural(warnings, "warning") }) : null)));
  if (focused) { const again = document.getElementById(focused); if (again) again.focus({ preventScroll: true }); }
}

function setSide(key) {
  const ed = editor;
  foldSide(false);
  ed.side = key;
  local.set("editSide", key);
  drawSideTabs();
  showSide();
}

function showSide() {
  const ed = editor;
  if (!ed.dom.sideBody) return;
  ed.dom.sideBody.setAttribute("aria-labelledby", `edit-side-${ed.side}`);
  clear(ed.dom.sideBody).append(ed.side === "add" ? ed.dom.addPart : ed.side === "stats" ? ed.dom.stats : ed.dom.check);
  if (ed.side === "stats") drawStats();
}

/** "/" and the bar's Add: the search box (the Add tab, or the Quick edit's search sheet). */
function focusSearch() {
  const ed = editor;
  if (!ed) return;
  if (ed.quick || !ed.dom.sideBody) { openAddSheet(); return; }
  if (ed.side !== "add") setSide("add");
  else foldSide(false);
  if (ed.ac) {
    ed.ac.input.focus();
    if (ed.ac.input.select) ed.ac.input.select();
  }
}

/** True while the list (the Deck, and a Commander deck's commander) has no cards: the size and the deck rules
 * have nothing to say yet. */
function emptyList() {
  const ed = editor;
  return !ed || mainCount(ed.lists, currentKind()) === 0;
}

// Stats -------------------------------------------------------------------------------

const SOURCE_TYPES = [["W", "Plains"], ["U", "Island"], ["B", "Swamp"], ["R", "Mountain"], ["G", "Forest"]];

/** The colours a card makes mana of: its basic land types, and each "Add ..." in its rules text. */
function manaSources(card) {
  const found = new Set();
  if (!card) return found;
  const type = card.type_line || "";
  for (const [c, land] of SOURCE_TYPES) if (type.includes(land)) found.add(c);
  for (const m of (card.oracle_text || "").matchAll(/\bAdd ([^.]*)/g)) {
    if (/any colou?r|any one colou?r|any combination of colou?rs/i.test(m[1])) "WUBRG".split("").forEach((c) => found.add(c));
    for (const s of m[1].matchAll(/\{([WUBRG])(?:\/[WUBRGP])?\}/g)) found.add(s[1]);
  }
  return found;
}

/** The list's numbers for the Stats tab: the curve of its spells, lands, colour sources and types. */
function listStats(ed = editor) {
  const kind = currentKind();
  const lines = (kind === "commander" ? ["Commander", "Deck"] : ["Deck"]).flatMap((s) => ed.lists[s] || []);
  const curve = Array(CURVE_TOP + 1).fill(0);
  const types = new Map();
  const sources = new Map();
  const colours = new Set();
  let lands = 0, spells = 0, mv = 0, total = 0;
  for (const line of lines) {
    const card = line.card;
    total += line.qty;
    const group = typeGroup(card);
    types.set(group, (types.get(group) || 0) + line.qty);
    if (!card) continue;
    const isLand = /\bLand\b/.test(card.type_line.split(" // ")[0]);
    if (isLand) lands += line.qty;
    else {
      spells += line.qty;
      mv += card.cmc * line.qty;
      curve[Math.min(CURVE_TOP, Math.floor(card.cmc))] += line.qty;
      for (const c of card.color_identity || []) colours.add(c);
    }
    for (const c of manaSources(card)) sources.set(c, (sources.get(c) || 0) + line.qty);
  }
  // The deck's colours: a commander's colour identity, else its spells'. Mana of any colour (a Command
  // Tower, an Arcane Signet) adds sources, not colours.
  const commanders = kind === "commander" ? (ed.lists.Commander || []).filter((l) => l.card) : [];
  const identity = commanders.length ? new Set(commanders.flatMap((l) => l.card.color_identity || [])) : colours;
  return { curve, lands, spells, total, average: spells ? mv / spells : 0, types, sources,
    colours: "WUBRG".split("").filter((c) => colours.has(c) || sources.has(c)),
    identity: "WUBRG".split("").filter((c) => identity.has(c)) };
}

function drawStats() {
  const ed = editor;
  const host = ed.dom.stats;
  if (!host || !host.isConnected) return;
  const s = listStats(ed);
  clear(host);
  if (!s.total) {
    host.append(el("p", { class: "empty", text: "Add cards to see the curve, lands and colours." }));
    return;
  }
  const top = Math.max(1, ...s.curve);
  const labels = s.curve.map((_, i) => (i === CURVE_TOP ? `${CURVE_TOP}+` : String(i)));
  add(host, [
    el("section", { class: "stat-block", "aria-labelledby": "h-curve" },
      el("h3", { id: "h-curve" }, "Mana curve", el("span", { class: "sub", text: ` · average ${num(s.average, 2)}` })),
      el("div", { class: "edit-curve", role: "img",
        "aria-label": `Spells by mana value: ${s.curve.map((n, i) => `${labels[i]}: ${n}`).join(", ")}` },
      s.curve.map((n, i) => el("div", { class: "curve-col", title: `${plural(n, "spell")} at mana value ${labels[i]}` },
        el("span", { class: "curve-n", text: n ? String(n) : "" }),
        el("span", { class: "curve-track" }, el("span", { class: "curve-bar", style: `height: ${Math.round((n / top) * 100)}%` })),
        el("span", { class: "curve-mv", text: labels[i] }))))),
    el("section", { class: "stat-block", "aria-labelledby": "h-lands" },
      el("h3", { id: "h-lands", text: "Lands" }),
      el("p", { class: "stat-line" }, el("b", { text: String(s.lands) }),
        ` of ${s.total} (${Math.round((s.lands / s.total) * 100)}%) · ${plural(s.spells, "spell")}`)),
    s.colours.length ? el("section", { class: "stat-block", "aria-labelledby": "h-sources" },
      el("h3", { id: "h-sources", text: "Colour sources" }),
      el("ul", { class: "stat-sources" }, s.colours.map((c) => el("li", {},
        symbolImg(c, { small: true, alt: COLOUR_WORDS[c] }), el("b", { text: String(s.sources.get(c) || 0) }))))) : null,
    el("section", { class: "stat-block", "aria-labelledby": "h-types" },
      el("h3", { id: "h-types", text: "Types" }),
      el("ul", { class: "stat-types" }, TYPE_GROUPS.filter((g) => s.types.get(g)).map((g) =>
        el("li", {}, el("span", { text: g }), el("b", { text: String(s.types.get(g)) })))))]);
}

// The bar at the bottom --------------------------------------------------------------

/** True while the play-now editor has no list yet (the deck has none and it hasn't been started). */
function noOwnedList() {
  const ed = editor;
  return ed.mode === "edit" && ed.version === "owned" && !ed.hasFileList && !ed.starting;
}

/** The bar's count, its checks button, Add (the Quick edit's) and the split Save. Its elements are made
 * once and then changed in place: a check that comes back (or a quantity typed) while a finger is on Save
 * doesn't swap the button from under it. */
function drawBar() {
  const ed = editor;
  const bar = ed.dom.bar;
  if (!bar) return;
  let p = ed.dom.barParts;
  if (!p || p.bar !== bar) {
    p = ed.dom.barParts = { bar,
      count: el("div", { class: "bar-count" }),
      checking: el("span", { class: "bar-checking", hidden: true },
        el("span", { class: "spinner spinner-small", "aria-hidden": "true" }), "Checking"),
      checks: el("button", { type: "button", class: "btn btn-quiet bar-warn", hidden: true, onclick: jumpToChecks }),
      dot: el("span", { class: "dot", role: "img", "aria-label": "(unsaved changes)", hidden: true }) };
    // The Quick edit's search sheet; below 1,100 px (editor.css) a jump to the Add panel above the list.
    p.addCards = noOwnedList() ? null : el("button", { type: "button", class: "btn bar-add" + (ed.quick ? "" : " bar-add-jump"),
      onclick: ed.quick ? openAddSheet : focusSearch }, "Add cards");
    if (!ed.readOnly) {
      p.save = el("button", { type: "button", class: "btn btn-primary bar-save", onclick: () => saveNow(),
        "data-focus": "save" }, ed.mode === "new" ? "Create" : "Save", p.dot);
      p.saveMore = ed.quick ? null : el("button", { type: "button", class: "btn btn-primary bar-save-more",
        "aria-label": "More ways to save", "aria-haspopup": "menu", text: "▾",
        onclick: () => openMenu(p.saveMore, [{ text: ed.mode === "new" ? "Create & view deck" : "Save & view deck",
          onclick: () => saveNow({ viewAfter: true }) }]) });
    }
    // variant.js (wave 3): "Test this change", before Save (a second row of its own below 700 px).
    p.test = typeof vtTestRow === "function" && !ed.quick ? vtTestRow() : null;
    clear(bar).append(p.count, p.checking, p.checks);
    add(bar, [p.addCards]);
    add(bar, [p.test, p.save]);
    add(bar, [p.saveMore]);
  }
  const kind = currentKind();
  const size = DECK_SIZE[kind];
  const n = mainCount(ed.lists, kind);
  const side = sectionCount(ed.lists, ["Sideboard"]);
  const ok = kind === "commander" ? n === size : n >= size;
  const state_ = ok ? "OK" : n < size ? `${size - n} short` : `${n - size} over`;
  const a = ed.check;
  const empty = n === 0;
  const blocks = (a ? a.blocks.length : 0) + (typedTitleProblem() ? 1 : 0);
  const warnings = a && !empty ? a.warnings.length : 0;
  const none = noOwnedList();
  if (none) {
    clear(p.count).append(el("span", { class: "bar-none", text: `No ${listName("owned", true)} yet` }));
    p.count.removeAttribute("aria-label");
  } else {
    // No size warning until the list has cards.
    add(clear(p.count), [
      el("span", { class: "bar-n" }, el("b", { text: String(n) }), el("span", { class: "bar-of", text: ` / ${size}` })),
      empty ? null : el("span", { class: `bar-sub${ok ? "" : " bar-short"}` }, state_, side ? ` · +${side} sideboard` : "")]);
    p.count.setAttribute("aria-label", `${n} of ${size} cards${kind === "commander" ? " with the commander" : ""}` +
      (empty ? "" : `, ${state_}`) + (side ? `, ${side} in the sideboard` : ""));
  }
  let words = null;
  if (ed.checkError) words = status("crit", "Not checked");
  else if (blocks || warnings) words = status(blocks ? "crit" : "warn", blocks ? plural(blocks, "problem") : plural(warnings, "warning"));
  p.checking.hidden = !(ed.checking && !a && !ed.checkError);
  p.checks.hidden = !words || !p.checking.hidden;
  if (words) clear(p.checks).append(words);
  p.dot.hidden = !(ed.dirty && ed.mode === "edit");
  // One primary per view: Save is the main action only while there's something to save (an unstarted
  // play-now list has its own "Start it" button).
  const mainSave = ed.mode === "new" || (ed.dirty && !none);
  for (const b of [p.save, p.saveMore]) if (b) b.classList.toggle("btn-primary", mainSave);
  if (p.save && !p.save.dataset.busy) p.save.disabled = none;
  if (p.test) {
    vtSyncTestRow(p.test);
    // Its reason ("Keep the same number of cards ...") is the button's tooltip here, not words in the bar.
    const why = p.test.vt && p.test.vt.why;
    if (why) p.test.vt.button.title = why.textContent || "";
  }
  drawSideTabs();
}

/** The bar's warnings: the Checks tab (or, in the Quick edit, the checks under the list). */
function jumpToChecks() {
  const ed = editor;
  if (ed.dom.sideBody) setSide("checks");
  const box = ed.dom.check;
  box.scrollIntoView({ block: "start" });
  box.focus({ preventScroll: true });
}
