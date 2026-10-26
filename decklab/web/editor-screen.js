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

Layout (editor.css): from 1,000 px the list, search and Stats/Checks form three panes; below that the original
Add/Stats/Checks tabs project their retained roots into one folded panel above the list. Notes has the whole
width; the full editor's shared card peek stays hidden so it cannot become a fourth pane. On a phone
(quickEditing) the editor is the Quick edit: compact rows with
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
  add(main, [ed.dom.page = el("div", { class: "edit-page" + (ed.quick ? " is-quick" : "") + (side ? " has-editor-panes" : "") },
    peekLayout(`edit:${ed.mode}:${ed.id || ed.from || ""}:${ed.version}`, firstCard(ed.lists), [
      crumb(back[0], back[1]),
      editorHead(),
      ed.dom.banners,
      work,
      side || !listOpen ? null : ed.dom.check,
      ed.dom.bar]))]);
  mountEditorPanes();
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

/** As decks.identity.deck_colors: readable commanders first, else Commander/Companion/Deck.
 * Sideboard and removed lines never define this current draft's decorative identity. No lookup is made. */
function editorDraftIdentity(ed) {
  const read = sections => {
    const found = [];
    for (const section of sections) {
      const lines = ed?.lists?.[section] || [];
      if (!Array.isArray(lines)) return null;
      for (const line of lines) {
        if (!line || !Number.isSafeInteger(line.qty) || line.qty < 1) return null;
        if (line.card == null) continue;
        const identity = line.card.color_identity;
        if (!Array.isArray(identity) || identity.length > 5 || new Set(identity).size !== identity.length
            || !Array.from(identity).every(c => typeof c === "string" && c.length === 1 && "WUBRG".includes(c))) return null;
        found.push(identity);
      }
    }
    return found;
  };
  const commanders = read(["Commander"]);
  if (commanders === null) return null;
  const found = commanders.length ? commanders : read(["Commander", "Companion", "Deck"]);
  if (!found?.length) return null;
  const colours = new Set(found.flat());
  return "WUBRG".split("").filter(c => colours.has(c));
}

/** Replace only decorative children, and only when identity changes; fields and their focus stay put. */
function drawEditorHeaderIdentity(ed = editor, initial = false) {
  const context = ed?.dom?.headerColour;
  if (!context || ed !== editor || ed.mode !== "edit" || ed.leaving || context.token !== routeToken
      || context.profile !== state.profile?.id || context.profile !== ed.profile || context.id !== ed.id
      || context.version !== ed.version || (!initial && !context.node.isConnected)) return;
  const identity = editorDraftIdentity(ed), key = JSON.stringify(identity);
  if (context.key === key) return;
  context.key = key;
  const pieces = identity === null ? null : deckColourPieces(identity);
  clear(context.node).append(pieces ? pieces.stripe() : el("span", { class: "deck-stripe is-unknown", "aria-hidden": "true" }),
    el("span", { class: "sr-only", text: `Current list colour identity. ${pieces ? pieces.label : "Not known"}.` }));
}

/** Resize reveals only the same focused control in this saved editor's original details fold. */
function revealEditorDetailsFocus() {
  const ed = editor, context = ed?.dom?.headerColour, page = ed?.dom?.page;
  const details = ed?.dom?.detailsSummary, fold = details?.closest(".edit-details-fold"), target = document.activeElement;
  const current = () => Boolean(ed && ed === editor && ed.mode === "edit" && context && ed.dom.headerColour === context
    && context.token === routeToken && context.profile === ed.profile && context.profile === state.profile?.id
    && context.id === ed.id && context.version === ed.version && page === ed.dom.page && page?.isConnected
    && context.node?.isConnected && page.contains(context.node) && details === ed.dom.detailsSummary
    && details?.closest(".edit-details-fold") === fold && fold?.isConnected && page.contains(fold)
    && target?.isConnected && fold.contains(target) && document.activeElement === target && !target.disabled
    && !target.matches(":disabled") && target.getAttribute("aria-disabled") !== "true" && !target.hidden
    && !target.closest("[hidden]") && (fold.open || fold.querySelector("summary")?.contains(target))
    && !ed.asking && !ed.leaving && !ed.saving && !document.querySelector("dialog[open]"));
  if (!current()) return;
  const reveal = () => {
    if (!current()) return;
    const rect = target.getBoundingClientRect(), vv = window.visualViewport;
    if (![rect.top, rect.bottom, rect.height].every(Number.isFinite) || rect.height <= 0) return;
    let top = Number.isFinite(vv?.offsetTop) ? Math.max(0, vv.offsetTop) : 0;
    let bottom = top + (Number.isFinite(vv?.height) && vv.height > 0 ? vv.height : window.innerHeight);
    const overlaps = r => r && r.height > 0 && r.right > rect.left && r.left < rect.right;
    const header = document.querySelector(".topbar")?.getBoundingClientRect();
    if (overlaps(header) && header.top <= top && header.bottom > top) top = header.bottom;
    const bar = ed.dom.bar?.isConnected ? ed.dom.bar.getBoundingClientRect() : null;
    if (overlaps(bar) && bar.bottom > top && bar.top < bottom) bottom = Math.max(top, bar.top);
    const available = bottom - top;
    if (available <= 0 || (rect.top >= top && rect.bottom <= bottom)) return;
    const oversized = rect.height > available;
    const gap = Math.min(8, oversized ? available / 4 : (available - rect.height) / 2);
    const first = top + gap, last = bottom - gap;
    // An oversized control aligns at its start once, rather than oscillating between both ends.
    const delta = oversized ? rect.top - first
      : rect.top < top ? rect.top - first : rect.bottom - last;
    if (Number.isFinite(delta) && Math.abs(delta) > .5) window.scrollBy({ top: delta, behavior: "auto" });
  };
  reveal();
  requestAnimationFrame(reveal); // Recheck this exact editor, fold and focus after layout settles.
}

window.addEventListener("resize", revealEditorDetailsFocus);
if (window.visualViewport) window.visualViewport.addEventListener("resize", revealEditorDetailsFocus);

function editorHead() {
  const ed = editor;
  const head = el("header", { class: "deck-head edit-head" });
  if (ed.mode === "edit") {
    head.classList.add("edit-head-saved");
    ed.dom.headerColour = { node: el("div", { class: "edit-head-colour" }), token: routeToken,
      profile: state.profile?.id, id: ed.id, version: ed.version, key: undefined };
    drawEditorHeaderIdentity(ed, true);
    head.append(ed.dom.headerColour.node, el("p", { class: "edit-kicker", text: "Editing" }),
      el("div", { class: "edit-title-row" },
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
  if (!list) syncEditorRowChanges(ed);
  syncEditorSearchQuantities(ed.ac);
  drawStats();
  drawDetailsSummary();
  drawEditorHeaderIdentity(ed);
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
  ed.dom.addPart = addPart();
  ed.dom.stats = el("div", { class: "edit-stats" });
  const search = el("section", { class: "edit-search-pane edit-side-body", id: "edit-pane-add" },
    el("h2", { class: "edit-pane-heading", id: "h-editor-add", tabindex: "-1", text: "Add cards" }), ed.dom.addPart);
  const stats = el("section", { class: "edit-stats-pane", id: "edit-pane-stats" },
    el("h2", { class: "edit-pane-heading", id: "h-editor-stats", tabindex: "-1", text: "Stats" }), ed.dom.stats);
  const facts = el("div", { class: "edit-facts-pane" }, stats, ed.dom.check);
  ed.dom.sideBody = el("div", { class: "edit-pane-grid", id: "edit-side-panel" }, search, facts);
  ed.dom.check.classList.add("edit-check-side");
  // Below 1,000 px (editor.css) the panel is folded to its tabs once the deck has cards, so the list starts on
  // the first screen; the fold button (and a tab, or Add cards) opens it.
  if (ed.sideFolded === undefined) ed.sideFolded = !emptyList();
  const context = ed.dom.panes = { ed, token: routeToken, hash: location.hash, profile: ed.profile, id: ed.id, version: ed.version,
    ac: ed.ac, search, facts, panels: { add: search, stats, checks: ed.dom.check },
    buttons: {}, page: null, root: null, building: true, wide: editorPanesWide() };
  ed.dom.sideFold = el("button", { type: "button", class: "btn btn-quiet edit-side-fold", "aria-controls": "edit-side-panel",
    onfocus: event => rememberEditorPaneHeader(context, event.currentTarget),
    onclick: () => { if (editorPanesCurrent(context)) foldSide(!ed.sideFolded); } });
  for (const [key, label] of SIDE_TABS) {
    const count = el("span", { class: "chip tab-count", role: "img", hidden: true });
    const button = el("button", { type: "button", role: "tab", id: `edit-side-${key}`,
      "data-pane": key, "aria-controls": context.panels[key].id,
      onfocus: event => rememberEditorPaneHeader(context, event.currentTarget),
      onclick: () => setSide(key, context) }, label, count);
    context.buttons[key] = { button, count };
    ed.dom.sideTabs.append(button);
  }
  const head = context.head = el("div", { class: "edit-side-head" }, ed.dom.sideTabs, ed.dom.sideFold);
  ed.dom.side = el("aside", { class: "panel edit-side", "aria-label": "Add, stats and checks" },
    head, ed.dom.sideBody);
  context.root = ed.dom.side;
  context.root.addEventListener("focusin", event => {
    if (editorPanesCurrent(context) && event.target !== context.rescuingHeader && editorPaneOf(context, event.target)) {
      revealEditorPaneFocus(context, event.target);
    }
  });
  drawSideTabs(context, true);
  projectEditorPanes(context);
  return ed.dom.side;
}

function editorPanesWide() { return window.matchMedia("(min-width: 1000px)").matches; }

/** The pane tree belongs to this exact editor draw; presentation never creates a new search. */
function editorPanesCurrent(context, building = false) {
  const ed = context?.ed;
  return Boolean(ed && editor === ed && ed.dom.panes === context && !ed.quick && !ed.leaving
    && context.token === routeToken && context.profile === state.profile?.id && context.profile === ed.profile
    && context.id === ed.id && context.version === ed.version && context.ac === ed.ac && !context.ac?.cancelled
    && context.root === ed.dom.side && (building && context.building || !context.building
      && context.page === ed.dom.page && context.page?.isConnected && context.page.contains(context.root)));
}

/** Only the editor's consumed swap/Notes URL may refresh this same tree's canonical address. */
function canonicalEditorPaneHash(ed, previousHash, canonicalHash) {
  const context = ed?.dom?.panes;
  if (!editorPanesCurrent(context) || context.ed !== ed || ed.mode !== "edit" || context.hash !== previousHash
      || canonicalHash !== editHref(ed.id, ed.version) || location.hash !== canonicalHash) return;
  context.hash = canonicalHash;
}

function mountEditorPanes() {
  const context = editor?.dom?.panes;
  if (!editorPanesCurrent(context, true) || !context.building) return;
  context.page = editor.dom.page;
  context.building = false;
  showSide();
}

function editorPaneOf(context, target) {
  if (!target) return null;
  return SIDE_TABS.find(([key]) => context.panels[key].contains(target))?.[0] || null;
}

/** Preserve a narrow tab's ownership through the browser's automatic blur when CSS hides the header. */
function rememberEditorPaneHeader(context, target) {
  if (!editorPanesCurrent(context) || context.wide || !context.head.contains(target)) return;
  context.headerFocus = { target, scope: JSON.stringify([context.ed.id, context.ed.version, context.ed.space]) };
}

function clearEditorPaneHeaderFocus(event) {
  const context = editor?.dom?.panes, held = context?.headerFocus;
  if (!editorPanesCurrent(context) || !held) return;
  const body = event.target === document.body || event.target === document.documentElement;
  if (body && context.projectingHeader === held) return;
  if (event.type === "pointerdown" ? !context.head.contains(event.target) : event.target !== held.target) {
    context.headerFocus = null;
  }
}

/** All roots stay attached. Only the casual projection uses the tabs and the saved fold preference. */
function projectEditorPanes(context) {
  const ed = context.ed, wide = context.wide;
  context.head.hidden = wide;
  ed.dom.sideBody.hidden = !wide && ed.sideFolded;
  ed.dom.side.classList.toggle("is-folded", ed.sideFolded);
  ed.dom.sideFold.textContent = ed.sideFolded ? "Show" : "Hide";
  ed.dom.sideFold.setAttribute("aria-expanded", String(!ed.sideFolded));
  context.facts.hidden = !wide && ed.side === "add";
  for (const [key, panel] of Object.entries(context.panels)) {
    panel.hidden = !wide && ed.side !== key;
    if (wide) panel.removeAttribute("role");
    else panel.setAttribute("role", "tabpanel");
    panel.setAttribute("aria-labelledby", wide ? ({ add: "h-editor-add", stats: "h-editor-stats", checks: "h-check" })[key]
      : `edit-side-${key}`);
  }
  const heading = ed.dom.check.querySelector("#h-check");
  if (heading) heading.setAttribute("class", wide ? "edit-pane-heading" : "sr-only");
}

/** Folds the side panel to its tabs (below 1,000 px; a wide screen always shows it), or opens it. */
function foldSide(folded) {
  const ed = editor, context = ed?.dom?.panes;
  if (!editorPanesCurrent(context)) return;
  const active = document.activeElement;
  if (folded && !context.wide && ed.dom.sideBody.contains(active) && !document.querySelector("dialog[open]")) {
    ed.dom.sideFold.focus({ preventScroll: true });
  }
  ed.sideFolded = folded;
  projectEditorPanes(context);
}

function drawSideTabs(context = editor?.dom?.panes, building = false) {
  if (!editorPanesCurrent(context, building)) return;
  const ed = context.ed;
  const a = ed.check;
  const blocks = (a ? a.blocks.length : 0) + (typedTitleProblem() ? 1 : 0);
  const warnings = a && !emptyList() ? a.warnings.length : 0;
  for (const [key, { button, count }] of Object.entries(context.buttons)) {
    button.setAttribute("aria-selected", String(ed.side === key));
    button.setAttribute("tabindex", ed.side === key ? "0" : "-1");
    count.hidden = key !== "checks" || !(blocks || warnings);
    if (!count.hidden) {
      count.setAttribute("class", `chip chip-${blocks ? "crit" : "warn"} tab-count`);
      count.textContent = String(blocks || warnings);
      count.setAttribute("aria-label", blocks ? plural(blocks, "problem") : plural(warnings, "warning"));
    }
  }
}

function setSide(key, context = editor?.dom?.panes) {
  if (!editorPanesCurrent(context) || !context.panels[key]) return;
  const ed = context.ed, active = document.activeElement;
  if (ed.tab !== "cards") { ed.tab = "cards"; drawMain(); }
  ed.side = key;
  ed.sideFolded = false;
  local.set("editSide", key);
  drawSideTabs();
  showSide();
  if (!context.wide && editorPaneOf(context, active) && editorPaneOf(context, active) !== key
      && !ed.saving && !ed.asking && !document.querySelector("dialog[open]")) {
    context.buttons[key].button.focus({ preventScroll: true });
  }
}

function showSide() {
  const context = editor?.dom?.panes;
  if (!editorPanesCurrent(context)) return;
  context.wide = editorPanesWide();
  projectEditorPanes(context);
  if (context.wide || context.ed.side === "stats") drawStats();
}

/** A resize may hide the casual tabs, but never the original focused or viewer-return pane. */
function resizeEditorPanes() {
  const context = editor?.dom?.panes;
  if (!editorPanesCurrent(context)) return;
  const ed = context.ed, active = document.activeElement, wide = editorPanesWide(), wasWide = context.wide;
  const pane = editorPaneOf(context, active);
  const held = wide && !wasWide ? context.headerFocus : null;
  const background = node => !node || node === document.body || node === document.documentElement;
  const rescue = held && held.target.isConnected && context.head.contains(held.target) && !held.target.disabled
    && held.scope === JSON.stringify([ed.id, ed.version, ed.space]) && (active === held.target || background(active)) ? held : null;
  // Read only the current viewer's exact return node; its close event may still be pending.
  const returnPane = typeof viewerState !== "undefined" && viewerState && viewerDom?.dialog?.contains(active)
    ? editorPaneOf(context, viewerState.trigger) : null;
  if (!wide && (pane || returnPane)) {
    ed.side = pane || returnPane;
    ed.sideFolded = false;
  }
  context.wide = wide;
  context.projectingHeader = rescue;
  projectEditorPanes(context);
  context.projectingHeader = null;
  const ownedHeader = rescue && context.headerFocus === rescue;
  if (wide && !wasWide) context.headerFocus = null;
  drawSideTabs();
  if (wide && !wasWide) drawStats();
  if (ed.tab !== "cards" || ed.saving || ed.asking || document.querySelector("dialog[open]")) return;
  if (ownedHeader && editorPanesCurrent(context)) {
    const key = rescue.target.dataset.pane || ed.side;
    const target = context.panels[key]?.querySelector("h2");
    if (target && (document.activeElement === rescue.target || background(document.activeElement))) {
      target.setAttribute("tabindex", "-1");
      context.rescuingHeader = target;
      target.focus({ preventScroll: true });
      context.rescuingHeader = null;
      revealEditorPaneFocus(context, target);
    }
  } else if (pane) revealEditorPaneFocus(context, active);
}

/** Scroll only the same owned focus, using the pane's actual scroller and the visible header/bar. */
function revealEditorPaneFocus(context, target) {
  const ed = context.ed, key = editorPaneOf(context, target);
  // A new deck can change space without rebuilding this tree. A queued scroll still belongs to its old scope.
  const scope = JSON.stringify([ed.id, ed.version, ed.space]), hash = location.hash;
  const owned = () => Boolean(editorPanesCurrent(context) && context.hash === hash && hash === location.hash && key && ed.tab === "cards"
    && scope === JSON.stringify([ed.id, ed.version, ed.space])
    && !target.disabled && !target.hidden && !target.closest("[hidden]") && !target.matches(":disabled")
    && target.getAttribute("aria-disabled") !== "true" && document.activeElement === target
    && target.isConnected && context.panels[key].contains(target) && !context.panels[key].hidden
    && !ed.dom.sideBody.hidden);
  const current = () => owned() && !ed.saving && !ed.asking && !document.querySelector("dialog[open]");
  // Native return focus may precede removal of the closing dialog's open state. Queue once for this same scope.
  if (!owned()) return;
  const scroll = () => {
    if (!current()) return;
    const scroller = key === "add" ? context.search : context.facts;
    const delta = () => {
      const rect = target.getBoundingClientRect(), bounds = scroller.getBoundingClientRect(), vv = window.visualViewport;
      if (![rect.top, rect.bottom, rect.height].every(Number.isFinite) || rect.height <= 0) return 0;
      let top = Number.isFinite(vv?.offsetTop) ? Math.max(0, vv.offsetTop) : 0;
      let bottom = top + (vv?.height > 0 ? vv.height : window.innerHeight);
      const overlaps = r => r && r.height > 0 && r.right > rect.left && r.left < rect.right;
      const header = document.querySelector(".topbar")?.getBoundingClientRect(), bar = ed.dom.bar?.getBoundingClientRect();
      if (overlaps(header) && header.top <= top && header.bottom > top) top = header.bottom;
      if (overlaps(bar) && bar.bottom > top && bar.top < bottom) bottom = Math.max(top, bar.top);
      if (context.wide && bounds.height > 0) { top = Math.max(top, bounds.top); bottom = Math.min(bottom, bounds.bottom); }
      const available = bottom - top;
      if (available <= 0 || rect.top >= top && rect.bottom <= bottom) return 0;
      const oversized = rect.height > available, gap = Math.min(8, oversized ? available / 4 : (available - rect.height) / 2);
      return oversized || rect.top < top ? rect.top - top - gap : rect.bottom - bottom + gap;
    };
    let by = delta();
    if (context.wide && Number.isFinite(by) && Math.abs(by) > .5 && current()) {
      scroller.scrollTop += by; // Native clamping is remeasured before falling back to the page.
      by = delta();
    }
    if (Number.isFinite(by) && Math.abs(by) > .5 && current()) window.scrollBy({ top: by, behavior: "auto" });
  };
  scroll();
  requestAnimationFrame(scroll);
}

/** Same-route viewer Back can restore scroll after its first focus frame. Never follow a real navigation. */
function revealEditorPaneHistoryFocus() {
  const context = editor?.dom?.panes, target = document.activeElement;
  if (!editorPanesCurrent(context) || context.hash !== location.hash || !editorPaneOf(context, target)) return;
  revealEditorPaneFocus(context, target);
}

window.matchMedia("(min-width: 1000px)").addEventListener("change", resizeEditorPanes);
window.addEventListener("resize", resizeEditorPanes);
window.addEventListener("popstate", revealEditorPaneHistoryFocus);
document.addEventListener("focusin", clearEditorPaneHeaderFocus);
document.addEventListener("pointerdown", clearEditorPaneHeaderFocus);

/** "/" and the bar's Add: the search box (the Add tab, or the Quick edit's search sheet). */
function focusSearch() {
  const ed = editor;
  if (!ed) return;
  if (ed.quick || !ed.dom.sideBody) { openAddSheet(); return; }
  if (!editorPanesCurrent(ed.dom.panes)) return;
  if (ed.tab !== "cards") { ed.tab = "cards"; drawMain(); }
  if (ed.side !== "add") setSide("add");
  else foldSide(false);
  if (editorSearchCurrent(ed.ac)) {
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

/** Only an actual saved list of this edit can be a comparison. Read-only trials still have that
 * readable baseline; new/copy/start-Play-now drafts do not. Unknown card data is not a zero count. */
function editorCurveBaseline(ed) {
  if (ed.mode !== "edit" || !ed.hasFileList || ed.starting || !["target", "owned"].includes(ed.version)) return null;
  const sections = currentKind() === "commander" ? ["Commander", "Deck"] : ["Deck"];
  const usable = line => line && Number.isSafeInteger(line.qty) && line.qty > 0 && line.card
    && typeof line.card.type_line === "string" && Number.isFinite(line.card.cmc) && line.card.cmc >= 0;
  const sameSpell = (a, b) => a.cmc === b.cmc
    && /\bLand\b/.test(a.type_line.split(" // ")[0]) === /\bLand\b/.test(b.type_line.split(" // ")[0]);
  if (!ed.base?.lists || !ed.lists) return null;
  const known = new Map(), projected = {};
  for (const section of sections) {
    const lines = ed.lists[section] || [];
    if (!Array.isArray(lines) || !lines.every(usable)) return null;
    for (const line of lines) {
      const other = known.get(line.name);
      if (other && !sameSpell(other, line.card)) return null;
      known.set(line.name, line.card);
    }
  }
  for (const section of sections) {
    const lines = ed.base.lists[section] || [];
    if (!Array.isArray(lines)) return null;
    projected[section] = [];
    for (const line of lines) {
      // A check can hydrate the draft after its saved copies were made. Reuse only same-name card
      // metadata in this local projection, never current quantities or a zero for missing metadata.
      const other = known.get(line?.name), card = line?.card || other;
      if (!usable({...line, card}) || (other && !sameSpell(card, other))) return null;
      projected[section].push({...line, card});
    }
  }
  return listStats({...ed, lists: projected}).curve;
}

/** Current spell counts keep their usual name; old-height marks and neutral deltas describe the saved
 * list on the same scale. The existing deck-colour helper owns the gradient, including colourless. */
function editorCurvePart(ed, stats, before) {
  const curve = stats.curve, top = Math.max(1, ...curve, ...(before || []));
  const labels = curve.map((_, i) => i === CURVE_TOP ? `${CURVE_TOP}+` : String(i));
  const changes = before ? curve.map((n, i) => n - before[i]) : curve.map(() => 0);
  const compared = changes.some(n => n !== 0);
  const saved = `saved ${listName(ed.version, true)}`;
  const changeWords = i => `${before[i]} saved, ${curve[i]} now (${Math.abs(changes[i])} ${changes[i] > 0 ? "more" : "fewer"})`;
  const words = `Spells by mana value: ${curve.map((n, i) => `${labels[i]}: ${n}`).join(", ")}`
    + (compared ? `. Compared with the ${saved}: ${changes.flatMap((n, i) => n ? [`${labels[i]}: ${changeWords(i)}`] : []).join(", ")}` : "");
  const identity = editorDraftIdentity(ed), colours = identity === null ? null : deckColourPieces(identity);
  const style = colours ? colours.vars().replace("linear-gradient(90deg", "linear-gradient(180deg") : "";
  const height = n => `${(100 * n / top).toFixed(1)}%`;
  return el("section", {class: "stat-block edit-curve-part", "aria-labelledby": "h-curve", style},
    el("h3", {id: "h-curve"}, "Mana curve", stats.spells
      ? el("span", {class: "sub", text: ` \u00b7 average ${num(stats.average, 2)}`}) : null),
    el("div", {class: "edit-curve", role: "img", "aria-label": words},
      curve.map((n, i) => el("div", {class: "curve-col", "aria-hidden": "true",
        title: `${plural(n, "spell")} at mana value ${labels[i]}` + (changes[i] ? `; ${changeWords(i)}` : "")},
        el("span", {class: "curve-n", text: n ? String(n) : ""}),
        el("span", {class: "curve-track"}, el("span", {class: "curve-bar", style: `height: ${height(n)}`}),
          changes[i] ? el("span", {class: `curve-before ${changes[i] > 0 ? "is-grown" : "is-shrunk"}`,
            style: `bottom: ${height(before[i])}`}) : null),
        el("span", {class: "curve-delta", text: changes[i] ? `${changes[i] > 0 ? "+" : "\u2212"}${Math.abs(changes[i])}` : ""}),
        el("span", {class: "curve-mv", text: labels[i]})))),
    compared ? el("p", {class: "curve-comparison", text: `Dashed marks and +/\u2212 counts compare this draft with the ${saved}.`}) : null);
}

function drawStats() {
  const ed = editor;
  const host = ed.dom.stats;
  if (!host || !host.isConnected) return;
  const s = listStats(ed);
  const before = editorCurveBaseline(ed);
  clear(host);
  if (!s.total) {
    const removedSpells = before?.some(n => n > 0);
    if (removedSpells) host.append(editorCurvePart(ed, s, before));
    host.append(el("p", { class: "empty", text: removedSpells
      ? "No cards in this draft. The curve compares it with the saved list."
      : "Add cards to see the curve, lands and colours." }));
    return;
  }
  add(host, [
    editorCurvePart(ed, s, before),
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
