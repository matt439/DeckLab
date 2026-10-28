/* Deck Lab's editor: Deck details (Milestone 4; the layout of UI-REVIEW.md WP11).

Loaded after editor.js and editor-screen.js and before editor-lines.js, editor-cards.js, editor-save.js
and editor-deckpage.js (then matchups.js and the page's other scripts, core.js to app.js). It holds the
Deck details part: a new deck's title and format, a saved deck's folded "Deck details" line and its
summary, the status, player, archetype and bracket fields, the Sleeves and Deck box tile pickers (with
"+ Add new ..." and the sleeves each deck needs), setField() and the stray lines a deck that isn't built
keeps only as Keep / Remove. It uses editor.js's constants, `editor`, fields and sheets, editor-screen.js's
FILE_FIELDS and changed(), and accessories.js's rows and Accessories sheet.
*/
"use strict";

// Deck details ------------------------------------------------------------------

/** A new deck: its title and format (and Whose deck, for an admin) in sight, the rest under "More details".
 * A saved deck: one folded "Deck details" line. The Quick edit keeps Status above the folded details. */
function detailsPart() {
  const ed = editor;
  ed.dom.details = el("div", { class: "field-grid" });
  let part;
  if (ed.mode === "new") {
    ed.dom.more = el("div", { class: "field-grid" });
    part = el("section", { class: "panel edit-details edit-details-new", "aria-label": "About the deck" }, ed.dom.details,
      el("details", { class: "more edit-more-details", open: ed.moreOpen || null,
        ontoggle: (e) => { ed.moreOpen = e.currentTarget.open; } },
      el("summary", {}, "More details"), ed.dom.more));
  } else if (ed.quick) {
    ed.dom.more = el("div", { class: "field-grid" });
    ed.dom.detailsSummary = el("span", { class: "details-summary" });
    part = el("section", { class: "edit-details edit-details-quick", "aria-label": "Deck details" }, ed.dom.details,
      el("details", { class: "panel edit-details edit-more-details edit-details-fold", open: ed.detailsOpen || null,
        ontoggle: (e) => { ed.detailsOpen = e.currentTarget.open; } },
      el("summary", {}, el("span", { class: "details-line" },
        el("span", { class: "details-title", text: "Deck details" }), ed.dom.detailsSummary)), ed.dom.more));
  } else {
    ed.dom.detailsSummary = el("span", { class: "details-summary" });
    part = el("details", { class: "panel edit-details edit-details-fold", open: ed.detailsOpen || null,
      ontoggle: (e) => { ed.detailsOpen = e.currentTarget.open; } },
    el("summary", {}, el("span", { class: "details-line" },
      el("span", { class: "details-title", text: "Deck details" }), ed.dom.detailsSummary)),
    ed.dom.details);
  }
  drawDetails();
  return part;
}

function drawDetails() {
  const ed = editor;
  const host = ed.dom.details;
  invalidatePlayerKitCatalog(ed);
  clear(host);
  const rest = ed.dom.more ? clear(ed.dom.more) : host;
  ed.kitNeeds = [];
  const f = ed.fields;
  if (ed.mode === "new") {
    const title = el("input", { type: "text", id: "f-title", value: f.title || "", maxlength: MAX_TITLE + 20,
      autocomplete: "off", enterkeyhint: "next", "aria-describedby": "f-title-hint", required: true,
      oninput: (e) => { f.title = e.target.value; drawTitleHint(); changed({ list: false }); } });
    ed.dom.titleHint = el("small", { class: "field-hint", id: "f-title-hint" });
    host.append(el("label", { class: "field field-title", for: "f-title" }, el("span", { text: "Title" }), title,
      ed.dom.titleHint));
    drawTitleHint();
    if (ed.from) {
      host.append(el("div", { class: "field" }, el("span", { text: "Format" }),
        el("p", { class: "field-fixed", text: KIND_WORDS[f.kind] })));
    } else {
      host.append(choiceField("kind", "Format", [["casual", "60-card"], ["commander", "Commander"]]));
    }
    add(host, [spaceField()]);
  }
  const status_ = choiceField("status", "Status", Object.entries(STATUS_WORDS));
  if (builtVersionGoes()) {
    status_.append(el("small", { class: "field-hint field-note", text: `Its Built version line (${fieldValueWords("built_version",
      ed.base.fields.built_version)}) goes too when it's saved: only a built deck has one.` }));
  }
  // Not for a person-space profile, who doesn't see the home's sleeves (the server still clears the lines).
  const kitSeen = mayDo("see_accessories");
  if (kitSeen && kitGo("sleeves")) {
    status_.append(el("small", { class: "field-hint field-note", text: `Its Sleeves line (${fieldValueWords("sleeves",
      ed.base.fields.sleeves)}) goes too when it's saved: its cards go back into storage unsleeved.` }));
  }
  if (kitSeen && kitGo("deck_box")) {
    status_.append(el("small", { class: "field-hint field-note", text: `Its Deck box line (${fieldValueWords("deck_box",
      ed.base.fields.deck_box)}) goes too when it's saved: only a built deck has one.` }));
  }
  (ed.quick && ed.mode === "edit" ? host : rest).append(status_);
  // A person's deck has no Played by (unless its text has one); at home a member picks only their own.
  if (ed.space === HOME_SPACE || ed.base.fields.player) rest.append(choiceField("player", "Played by", allowedPlayers()));
  if (editorPlayerKitVisible(ed) && (Object.hasOwn(ed, "playerKitRows") || ed.fields.player !== ed.base.fields.player)) {
    rest.append(el("button", {type: "button", class: "btn", text: "Review player and kit", onclick: event => {
      if (event.currentTarget.isConnected && ed.dom.page?.contains(event.currentTarget) && editor === ed) reviewPlayerKit(ed.fields.player);
    }}));
  }
  const archetype = el("input", { type: "text", id: "f-archetype", value: f.archetype || "", maxlength: 300,
    autocomplete: "off", enterkeyhint: "done", placeholder: "e.g. Boros burn: cheap attackers, then burn to finish",
    oninput: (e) => { f.archetype = e.target.value; changed({ list: false }); } });
  rest.append(el("label", { class: "field field-wide", for: "f-archetype" }, el("span", { text: "Archetype" }), archetype));
  if (fieldOffered("built_version")) {
    if (strayBuiltVersion()) {
      // Written by hand on a deck that isn't built: it can only go.
      const was = ed.base.fields.built_version;
      rest.append(choiceField("built_version", "Built version",
        [[was, `Keep “${fieldValueWords("built_version", was)}”`], [null, "Remove it"]],
        "Only a built deck has a Built version."));
    } else {
      rest.append(choiceField("built_version", "Built version",
        [["target", listName("target")], ["owned", listName("owned")]]));
    }
  }
  if (fieldOffered("sleeves")) rest.append(sleevesField());
  if (fieldOffered("deck_box")) rest.append(deckBoxField());
  if (fieldOffered("target_bracket")) rest.append(bracketField());
  drawDetailsSummary();
}

/** A field whose value is picked from a few buttons (aria-pressed). */
function choiceField(key, label, options, hint) {
  const ed = editor;
  const id = `f-${key}`;
  const group = el("div", { class: "segmented", role: "group", "aria-labelledby": id });
  for (const [value, text] of options) {
    group.append(el("button", { type: "button", "aria-pressed": String(ed.fields[key] === value),
      "data-focus": `field:${key}:${value}`, onclick: event => {
        if (key === "player" && (editor !== ed || !event.currentTarget.isConnected || !ed.dom.page?.contains(event.currentTarget))) return;
        setField(key, value);
      } }, text));
  }
  const fileText = fileWords(key);
  return el("div", { class: "field" }, el("span", { id, text: label }), group,
    fileText ? el("small", { class: "field-hint", text: fileText }) : null,
    hint ? el("small", { class: "field-hint", text: hint }) : null);
}

/** "The deck says “either. Suits whoever...”": a field written with more words than its value. A save
 * changes only the first word (decks.set_status / set_player keep the rest). */
function fileWords(key) {
  const ed = editor;
  if (ed.mode !== "edit" || !FILE_FIELDS[key]) return null;
  const text = ed.view.field_text[FILE_FIELDS[key]];
  const value = ed.base.fields[key];
  if (!text || (value && text.trim().toLowerCase() === String(value).toLowerCase())) return null;
  return `The deck says “${text.trim().replace(/[.!?]$/, "")}”.` + (value ? " Picking another changes only its first word." : "");
}

/** Sleeves: a tile picker of the accessories list's sleeves for a built deck, or Keep / Remove for a line
 * left on a deck that isn't built. */
function sleevesField() { return kitField("sleeves"); }

/** Deck box: the same for the accessories list's deck boxes. */
function deckBoxField() { return kitField("deck_box"); }

const KIT_PICK_WORDS = {
  sleeves: { add: "+ Add new sleeves", stray: "The deck has a Sleeves line, but it isn't built: only a built deck has sleeves.",
    loading: "Loading your sleeves…", what: "Your sleeves" },
  deck_box: { add: "+ Add a new deck box", stray: "The deck has a Deck box line, but it isn't built: only a built deck has one.",
    loading: "Loading your deck boxes…", what: "Your deck boxes" },
};

/** A Sleeves or Deck box field (role=radiogroup): None, every row of that kind in the accessories list
 * (sleeves other decks use can be chosen too, and say so; a deck box with none free is disabled), the file's
 * older free text as "Keep “x”", and "+ Add new ...",
 * which adds a row on the Accessories sheet and picks it. Saved with the deck as the row's id. */
function kitField(key) {
  const ed = editor;
  const words = KIT_PICK_WORDS[key];
  if (strayKit(key)) {
    const was = ed.base.fields[key];
    return choiceField(key, FIELD_WORDS[key], [[was, `Keep “${kitName(key, was)}”`], [null, "Remove it"]], words.stray);
  }
  loadKitRows();
  if (editorPlayerKitCatalogNeeded(ed)) return playerKitCatalogField(ed, key);
  const id = `f-${key}`;
  const current = norm(key, ed.fields[key]);
  const rows = kitRows(key);
  // Older free text (the file's, or the draft's) stays pickable until something else is saved.
  const texts = [...new Set([ed.mode === "edit" ? norm(key, ed.base.fields[key]) : null, current])]
    .filter((v) => v && !rows.some((row) => row.id === v) && (!ed.playerKitItems || !editorPlayerKitKnownId(ed, v)));
  const options = [{ value: null, text: "None", sub: "Not recorded yet" },
    ...texts.map((v) => ({ value: v, text: `Keep “${v}”`, sub: "Not in the accessories list" })),
    ...rows.map((row) => ({ value: row.id, row }))];
  const group = el("div", { class: "kit-pick", role: "radiogroup", "aria-labelledby": id,
    onkeydown: (e) => kitArrow(e, key) });
  const chosenAt = Math.max(0, options.findIndex((o) => o.value === current));
  options.forEach((o, i) => group.append(kitTile(key, o, o.value === current, i === chosenAt)));
  const addButton = el("button", { type: "button", class: "btn btn-quiet kit-add", "data-focus": `field:${key}:add`,
    onclick: () => addKitRow(key) }, words.add);
  const others = key === "sleeves" ? (ed.view && ed.view.other_sleeves || []).map((o) => `${o.sleeves} (${o.title})`) : [];
  return el("div", { class: "field field-wide kit-field", "data-kit": key }, el("span", { id, text: FIELD_WORDS[key] }),
    group, addButton,
    current && !options.some(option => option.value === current) ? el("p", {class: "field-hint", text:
      `Current draft choice: ${current} is unavailable for this player. Choose a replacement or None; the draft is kept until you choose.`}) : null,
    others.length ? el("small", { class: "field-hint", text: `Other decks' sleeves: ${others.join(", ")}.` }) : null,
    ed.accLoad === "loading" ? loadingBox(words.loading, { small: true })
      : ed.accLoad === "failed" ? loadFailed(words.what, ed.accError, retryKitRows) : null);
}

/** One tile of a kit picker: a radio with the row's picture, name and, for sleeves, whether there are
 * enough for the list as it is now (drawKitNeeds keeps that up to date as cards change). */
function kitTile(key, option, chosen, tabbable) {
  const ed = editor;
  const row = option.row;
  const taken = row ? kitTaken(key, row) : { others: [], taken: false };
  const sub = el("small", { class: "kit-tile-sub", text: option.sub || "" });
  const button = el("button", { type: "button", class: "kit-tile", role: "radio", "aria-checked": String(chosen),
    tabindex: tabbable ? "0" : "-1", "data-focus": `field:${key}:${option.value}`, disabled: (taken.taken && !chosen) || null,
    "data-shared": key === "sleeves" && row && taken.others.length && !chosen ? "true" : null,
    onclick: () => { if (!chosen) pickKitTile(key, option, taken); } },
  kitTileThumb(row, option.value),
  el("span", { class: "kit-tile-text" }, el("strong", { text: row ? row.label : option.text }), sub,
    taken.none ? el("small", { class: "kit-tile-taken", text: "None left (quantity 0)" })
      : taken.others.length ? el("small", { class: taken.taken ? "kit-tile-taken" : "kit-tile-sub",
        text: `${key === "sleeves" ? "Also used by" : "In use:"} ${taken.others.map((h) => h.title).join(", ")}` }) : null));
  if (row) {
    (ed.kitNeeds || (ed.kitNeeds = [])).push({ key, row, sub });
    kitNeedWords(key, row, sub);
  }
  return button;
}

/** Choose a kit tile. Sleeves other decks already use are warned about first (E8-S20, 2026-10-19): sharing a
 * design is allowed, so it asks rather than refuses (E8-S20). A deck box with none free can't be clicked. */
async function pickKitTile(key, option, taken) {
  const ed = editor;
  if (key === "sleeves" && option.row && taken.others.length) {
    const names = taken.others.map((h) => h.title).join(", ");
    const choice = await askAccessoryChoice(`Use ${option.row.label} here too?`,
      [`${names} ${taken.others.length === 1 ? "uses" : "use"} these sleeves already. `
        + "Several decks can share one design: just don't play two of them against each other."],
      [{ text: "Use them here too", kind: "primary", value: "share" }, { text: "Cancel", value: null }]);
    if (choice !== "share" || editor !== ed) return;       // cancelled, or the editor was left meanwhile
  }
  setField(key, option.value);
}

/** A kit tile's picture: the row's (accessories.js accessoryThumb), the first letter of older free text, or for
 * None the dashed "None chosen" slot used wherever nothing is chosen. Decoration: the tile's words name it. */
function kitTileThumb(row, value) {
  const thumb = accessoryThumb(row || (value ? { label: value, value } : null), 48);
  thumb.setAttribute("aria-hidden", "true");
  return thumb;
}

/** A row's quantity against what the deck needs: "75 needed · 100 owned · 25 spare", "15 short · 60 owned". */
function kitNeedWords(key, row, sub) {
  const quantity = Number(row.quantity) || 0;
  if (key !== "sleeves") {
    const need = kitNeed();
    const capacity = row.capacity == null ? null : Number(row.capacity);
    sub.textContent = capacity == null ? plural(quantity, "box", "boxes")
      : need > capacity ? `Too small: holds ${capacity}, ${need} cards` : `Holds ${capacity} · ${plural(quantity, "box", "boxes")}`;
    return;
  }
  const need = kitNeed();
  const short = need - quantity;
  sub.textContent = !need ? plural(quantity, "sleeve") : short > 0 ? `${short} short · ${quantity} owned`
    : `${need} needed · ${quantity} owned · ${quantity - need} spare`;
  sub.className = short > 0 ? "kit-tile-sub kit-tile-short" : "kit-tile-sub";
}

/** The sleeves tiles' counts, after a change to the list (or the Built version) changes what's needed. */
function drawKitNeeds() {
  for (const { key, row, sub } of editor.kitNeeds || []) kitNeedWords(key, row, sub);
}

/** Arrow keys move through a kit picker's tiles and pick, as radio buttons do; a tile whose sleeves
 * other decks have only gets the focus (Enter or Space picks it, after the warning), so arrowing past it
 * never opens the warning. */
function kitArrow(e, key) {
  if (!editorKeyboardCurrent() || editor.saving || editor.asking || editor.leaving
    || editorKeyIgnored(e) || keyboardMenuOpen() || document.querySelector("dialog[open]")
    || e.ctrlKey || e.metaKey || e.altKey || e.shiftKey || !editor?.dom?.page?.contains(e.currentTarget)) return;
  const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
  if (!step) return;
  const tiles = [...e.currentTarget.querySelectorAll(".kit-tile")].filter((t) => !t.disabled);
  const at = tiles.indexOf(document.activeElement);
  if (at < 0 || tiles.length < 2) return;
  e.preventDefault();
  const next = tiles[(at + step + tiles.length) % tiles.length];
  if (next.dataset.shared !== "true") { next.click(); return; }
  for (const tile of tiles) tile.tabIndex = tile === next ? 0 : -1;
  next.focus();
}

/** A new deck from scratch has no edit view: its pickers load the accessories list once. */
function loadKitRows() {
  const ed = editor;
  if (editorPlayerKitCatalogNeeded(ed)) { loadPlayerKitCatalog(ed); return; }
  if (ed.playerKitCatalog) { ed.playerKitCatalog = null; ed.accLoad = null; ed.accError = null; }
  if (ed.mode !== "new" || ed.accRows || (ed.view && ed.view.accessories) || ed.accLoad) return;
  ed.accLoad = "loading";
  api("/api/accessories").then((data) => {
    if (editor !== ed) return;
    ed.accRows = kitRowsOf(data.items, accessoryOwnerOf(ed.fields.player));
    ed.accLoad = "done";
    redrawKitFields();
  }, (error) => {
    if (editor !== ed) return;
    ed.accLoad = "failed";
    ed.accError = error;
    redrawKitFields();
  });
}

/** The edit view's owner-filtered, ownerless rows cannot serve a different player after resume/rebase. */
function editorPlayerKitCatalogNeeded(ed) {
  return editorPlayerKitEditable(ed) && ed.fields.status === "built" && !ed.playerKitItems
    && norm("player", ed.fields.player) !== norm("player", ed.base.fields.player);
}
function editorPlayerKitKnownId(ed, id) {
  return ed.playerKitItems?.some(row => row.id === id) || copiedPlayerKitRows(ed.playerKitRows)?.some(row => row.id === id)
    || KIT_FIELDS.some(key => ed.view?.accessories?.[key]?.some(row => row.id === id));
}
function playerKitCatalogKey(ed) {
  return JSON.stringify([ed.id, ed.version, ed.space, ed.sha256, ed.base.fields.player,
    ed.fields.player, ed.fields.status, ed.fields.sleeves, ed.fields.deck_box, ed.playerKitRows]);
}
function invalidatePlayerKitCatalog(ed) {
  const record = ed.playerKitCatalog;
  if (record && (record.key !== playerKitCatalogKey(ed) || record.host !== ed.dom.details || record.view !== ed.view
      || record.token !== routeToken || record.profile !== state.profile?.id)) {
    ed.playerKitCatalog = null; ed.accLoad = null; ed.accError = null;
  }
}
function playerKitCatalogCurrent(ed, record) {
  return editor === ed && ed.playerKitCatalog === record && ed.profile === state.profile?.id && record.profile === ed.profile
    && record.token === routeToken && record.view === ed.view && record.host === ed.dom.details && record.host.isConnected
    && ed.dom.page?.contains(record.host) && !ed.leaving && editorPlayerKitCatalogNeeded(ed) && record.key === playerKitCatalogKey(ed);
}
function loadPlayerKitCatalog(ed) {
  if (editor !== ed || ed.profile !== state.profile?.id || ed.leaving || !ed.dom?.details
      || ed.entryToken != null && ed.entryToken !== routeToken) return;
  const key = playerKitCatalogKey(ed), previous = ed.playerKitCatalog;
  if (previous && previous.key === key && previous.host === ed.dom.details && previous.view === ed.view
      && previous.token === routeToken && previous.profile === state.profile?.id) return;
  const record = {key, host: ed.dom.details, view: ed.view, token: routeToken, profile: ed.profile, status: "loading", error: null};
  ed.playerKitCatalog = record; ed.accLoad = "loading"; ed.accError = null;
  if (!["shared", ed.profile].includes(accessoryOwnerOf(ed.fields.player))) {
    record.status = "blocked"; ed.accLoad = null; return;
  }
  api("/api/accessories").then(answer => {
    if (!playerKitCatalogCurrent(ed, record)) return;
    ed.playerKitItems = editorPlayerKitItems(answer.items);
    ed.playerKitCatalog = null; ed.accLoad = "done"; ed.accError = null;
    redrawKitFields();
  }).catch(error => {
    if (!playerKitCatalogCurrent(ed, record)) return;
    record.status = "failed"; record.error = error; ed.accLoad = "failed"; ed.accError = error;
    redrawKitFields();
  });
}
function playerKitCatalogField(ed, key) {
  const record = ed.playerKitCatalog, words = KIT_PICK_WORDS[key];
  const field = el("div", {class: "field field-wide kit-field", "data-kit": key}, el("span", {text: FIELD_WORDS[key]}),
    el("p", {class: "field-hint", text: `Current draft: ${norm(key, ed.fields[key]) || "None"}. Choices for this player have not been checked yet.`}));
  if (record?.status === "blocked") {
    field.append(el("p", {class: "field-hint", text: "That player's kit is theirs to choose. Ask its owner to hand the deck on."}));
  } else if (record?.status === "failed") {
    const problem = loadFailed(words.what, record.error, () => {
      const button = problem.querySelector("button");
      if (!button?.isConnected || !field.contains(button) || record.status !== "failed" || !playerKitCatalogCurrent(ed, record)) return;
      ed.playerKitCatalog = null; ed.accLoad = null; ed.accError = null;
      loadKitRows(); redrawKitFields();
    });
    field.append(problem);
  } else field.append(loadingBox(words.loading, {small: true}));
  return field;
}

/** Try again after the accessories list couldn't be loaded: load it, showing the pickers' loading line. */
function retryKitRows() {
  const ed = editor;
  if (!ed || ed.accLoad !== "failed") return;
  ed.accLoad = null;
  ed.accError = null;
  loadKitRows();
  redrawKitFields();
}

/** Draw the kit pickers again in place (the rest of Deck details, and what has focus there, stays). */
function redrawKitFields() {
  const ed = editor;
  if (!ed.dom || !ed.dom.details) return;
  ed.kitNeeds = (ed.kitNeeds || []).filter((n) => !KIT_FIELDS.includes(n.key));
  for (const key of KIT_FIELDS) {
    const host = ed.dom.more || ed.dom.details;
    const now = host.querySelector(`[data-kit="${key}"]`);
    if (now && fieldOffered(key) && !strayKit(key)) now.replaceWith(kitField(key));
  }
}

/** "+ Add new sleeves": add a row on the Accessories sheet, then pick it here (saved with the deck). */
function addKitRow(key) {
  const ed = editor;
  const owner = accessoryOwnerOf(ed.fields.player);
  openAccessorySheet({ kind: key, lockKind: true, owner, onSaved: (answer, words) => {
    toast(words);
    if (editor !== ed) return;
    if (ed.playerKitItems) {
      // A successful accessory add must stay successful even when its optional cache cannot be refreshed.
      try { ed.playerKitItems = editorPlayerKitItems(answer.data?.items); } catch (_) { ed.playerKitItems = null; }
    }
    ed.accRows = kitRowsOf(answer.data && answer.data.items, owner);
    const row = kitRows(key).find((r) => r.id === answer.changed_id);
    if (row && fieldOffered(key) && !strayKit(key)) setField(key, row.id);
    else redrawKitFields();
  } });
}

function bracketField() {
  const ed = editor;
  const names = new Map((ed.brackets || []).map((b) => [b.number, b.name]));
  const select = el("select", { id: "f-target_bracket", "data-focus": "field:target_bracket",
    onchange: (e) => setField("target_bracket", e.target.value ? Number(e.target.value) : null, false) },
  el("option", { value: "", text: "Not set" }),
  [1, 2, 3, 4, 5].map((n) => el("option", { value: n, selected: ed.fields.target_bracket === n || null,
    text: names.has(n) ? `${n}: ${names.get(n)}` : `Bracket ${n}` })));
  return el("label", { class: "field", for: "f-target_bracket" }, el("span", { text: "Target bracket" }), select);
}

function drawTitleHint() {
  const hint = editor.dom.titleHint;
  if (!hint) return;
  const typed = norm("title", editor.fields.title);
  const problem = typed ? titleProblem() : null;
  hint.className = "field-hint" + (problem ? " field-problem" : "");
  hint.textContent = problem || "";
}

function setField(key, value, redraw = true) {
  const ed = editor;
  if (key === "player" && value !== ed.fields.player && editorPlayerKitVisible(ed)) {
    reviewPlayerKit(value); return;
  }
  ed.fields[key] = value;
  if (KIT_FIELDS.includes(key)) updateEditorPlayerKitChoice(ed, key, value);
  if (key === "kind") {
    // A casual deck has no Commander section: its cards go into the Deck.
    const commanders = ed.lists.Commander || [];
    if (value === "casual" && commanders.length) {
      // A printing the Deck has already goes on its line (the file would have one line for it).
      const deck = ed.lists.Deck || (ed.lists.Deck = []);
      [...commanders].reverse().forEach((line) => {
        const same = deck.find((l) => lineKey(l) === lineKey(line));
        if (same) same.qty = Math.min(MAX_COPIES, same.qty + line.qty);
        else deck.unshift(line);
      });
      delete ed.lists.Commander;
      toast("A casual deck has no Commander section, so those cards are in the Deck now.");
    }
    if (value === "casual") ed.removed = ed.removed.filter((g) => g.section !== "Commander");
    syncSections();
    changed();
    drawEditor();
    return;
  }
  if (key === "status") resetStrayFields();
  if (redraw) drawDetails();
  changed({ list: false });
  if (redraw) {
    const host = ed.dom.details.parentNode || ed.dom.details;
    const again = host.querySelector(`[data-focus="field:${key}:${value}"]`);
    if (again) again.focus({ preventScroll: true });
  }
}

function editorPlayerKitEditable(ed) {
  return ed?.mode === "edit" && ed.space === HOME_SPACE && !ed.readOnly
    && mayDo("accessories") && KIT_FIELDS.every(key => ed.view?.editable_fields?.includes(key));
}
/** Hidden null kit fields never prove a held kit exists. Only an editable visible kit prompts here. */
function editorPlayerKitVisible(ed) {
  return editorPlayerKitEditable(ed) && ed.fields.status === "built"
    && KIT_FIELDS.some(key => norm(key, ed.fields[key]) || norm(key, ed.base.fields[key]));
}

/** A player change carries its complete final kit through normal check/Save, including explicit clears. */
function editorPlayerKitFields(ed, fields, body) {
  const marked = Object.hasOwn(ed, "playerKitRows");
  const rows = marked ? copiedPlayerKitRows(ed.playerKitRows) : null;
  // A valid marker is irrelevant while taking the deck apart, when its kit is cleared.
  // Keep it locally for Undo/toggling back; a damaged marker always stays a blocking request.
  if (body && marked && (rows === null || ed.fields.status === "built")) body.kit_rows = rows;
  if (editorPlayerKitEditable(ed) && ed.fields.status === "built"
      && (marked || norm("player", ed.fields.player) !== norm("player", ed.base.fields.player))) {
    fields.player = norm("player", ed.fields.player);
    for (const key of KIT_FIELDS) fields[key] = norm(key, ed.fields[key]);
  }
  return fields;
}

/** Missing old metadata remains legacy-compatible; malformed present intent stays an explicit invalid marker. */
function copiedPlayerKitRows(raw) {
  if (!Array.isArray(raw) || raw.length > 2) return null;
  const seen = new Set(), out = [];
  for (const row of raw) {
    if (!row || Object.keys(row).sort().join(",") !== "field,id" || !KIT_FIELDS.includes(row.field) || seen.has(row.field)
        || typeof row.id !== "string" || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(row.id) || row.id.length > 40) return null;
    seen.add(row.field); out.push(Object.freeze({field: row.field, id: row.id}));
  }
  return Object.freeze(out.sort((a, b) => KIT_FIELDS.indexOf(a.field) - KIT_FIELDS.indexOf(b.field)));
}
function editorPlayerKitSnapshot(ed) {
  return Object.hasOwn(ed, "playerKitRows") ? {playerKitRows: copiedPlayerKitRows(ed.playerKitRows)} : {};
}
function restoreEditorPlayerKit(ed, saved) {
  if (Object.hasOwn(saved, "playerKitRows")) ed.playerKitRows = copiedPlayerKitRows(saved.playerKitRows);
  else delete ed.playerKitRows;
  return saved;
}
function updateEditorPlayerKitChoice(ed, field, value) {
  const marked = Object.hasOwn(ed, "playerKitRows");
  if (!marked && !(ed.playerKitItems && ed.mode === "edit" && ed.fields.player !== ed.base.fields.player)) return;
  const rows = marked ? copiedPlayerKitRows(ed.playerKitRows) : [];
  if (rows === null) return; // only a full explicit review replaces damaged intent
  const next = rows.filter(row => row.field !== field), row = kitRows(field).find(item => item.id === norm(field, value));
  if (row) next.push({field, id: row.id});
  ed.playerKitRows = copiedPlayerKitRows(next);
}

/** A copied, bounded choice cache keeps Undo's current player independent of the prior filtered view. */
function editorPlayerKitItems(items) {
  if (!Array.isArray(items) || items.length > 1000) throw new Error("The accessories list could not be checked.");
  let holders = 0;
  return Object.freeze(items.filter(item => item && item.editable !== false && KIT_FIELDS.includes(item.kind)
    && (item.owner === "shared" || item.owner === state.profile?.id)).map(item => {
    if (!["id", "owner", "label"].every(key => typeof item[key] === "string" && item[key].length <= 500)
        || !Number.isInteger(item.quantity) || item.quantity < 0 || item.quantity > 9999
        || item.capacity != null && (!Number.isInteger(item.capacity) || item.capacity < 1 || item.capacity > 9999)
        || item.colour != null && (typeof item.colour !== "string" || item.colour.length > 500)
        || item.image_url != null && (typeof item.image_url !== "string" || item.image_url.length > 3000)
        || !Array.isArray(item.used_by) || (holders += item.used_by.length) > 20000
        || item.used_by.some(holder => !holder || typeof holder.title !== "string" || holder.title.length > 500
          || holder.holder != null && (typeof holder.holder !== "string" || holder.holder.length > 500)))
      throw new Error("The accessories list could not be checked.");
    return Object.freeze({id: item.id, kind: item.kind, owner: item.owner, label: item.label, editable: true,
      colour: item.colour || null, quantity: item.quantity, capacity: item.capacity ?? null, image_url: item.image_url || null,
      used_by: Object.freeze(item.used_by.map(holder => Object.freeze({holder: holder.holder, title: holder.title,
        kind: typeof holder.kind === "string" ? holder.kind : null, need: Number.isSafeInteger(holder.need) ? holder.need : null})))});
  }));
}

/** Review the player and both kit fields as one local draft step; no accessory or deck write happens here. */
async function reviewPlayerKit(player) {
  const ed = editor;
  if (!editorPlayerKitVisible(ed) || ed.saving || ed.asking || ed.promoting || ed.leaving || ed.profile !== state.profile?.id
      || !ed.dom.page?.isConnected || !allowedPlayers().some(([value]) => value === player)) return null;
  const initial = JSON.stringify([ed.sha256, ed.fields, ed.lists]), token = routeToken;
  const sheet = openSheet({title: "Review player and kit", wide: true});
  const owner = editorWriteOwner(ed, sheet);
  const current = () => owner() && !ed.saving && !ed.asking && !ed.promoting && token === routeToken
    && initial === JSON.stringify([ed.sha256, ed.fields, ed.lists]);
  const nextOwner = accessoryOwnerOf(player);
  const playerName = player === "either" ? "Either" : playerWords(player);
  sheet.body.append(el("p", {text: `Change Played by to ${playerName}, with sleeves and a deck box chosen for that player.`}));
  const cancel = () => sheet.close();
  sheetActions(sheet, [{text: "Keep editing", onclick: cancel}]);
  // Read access to another owner's public kit grants no choice or hand-off authority.
  if (nextOwner !== "shared" && nextOwner !== state.profile.id) {
    sheet.body.append(el("p", {class: "box box-info", text:
      "That player's kit is theirs to choose. Ask its owner to hand the deck on; this draft stays as it is."}));
    return sheet;
  }
  const body = el("div", {}, loadingBox("Loading permitted sleeves and deck boxes."));
  sheet.body.append(body);
  let items;
  try {
    const answer = await api("/api/accessories");
    if (!current()) return sheet;
    items = editorPlayerKitItems(answer.items);
  } catch (error) {
    if (current()) {
      clear(body).append(loadFailed("Permitted sleeves and deck boxes", error, () => {
        if (!current()) return; sheet.close(); reviewPlayerKit(player);
      }));
    }
    return sheet;
  }
  clear(body);
  const choices = Object.fromEntries(KIT_FIELDS.map(key => [key, norm(key, ed.fields[key])]));
  const permitted = items.filter(item => item && item.editable !== false && accessoryUsable(item, nextOwner));
  const known = new Set([...items.map(row => row.id), ...KIT_FIELDS.flatMap(key => kitRows(key).map(row => row.id))]);
  const rows = Object.fromEntries(KIT_FIELDS.map(key => [key, permitted.filter(row => row.kind === key)]));
  const controls = {}, review = el("dl", {class: "review-facts"}), sharing = el("p", {class: "box box-info", hidden: true});
  const acceptedSharing = el("input", {type: "checkbox"});
  const shareControl = el("label", {class: "field", hidden: true}, acceptedSharing,
    el("span", {text: "Use this sleeves design here too; these decks won't play each other."}));
  let applyButton = null;
  const words = (key, value) => value == null ? "None" : rows[key].find(row => row.id === value)?.label || value;
  function drawReview() {
    if (!current()) return;
    acceptedSharing.checked = false;
    clear(review).append(el("div", {}, el("dt", {text: "Played by"}), el("dd", {text: playerName})),
      ...KIT_FIELDS.map(key => el("div", {}, el("dt", {text: FIELD_WORDS[key]}), el("dd", {text:
        choices[key] === "__choose__" ? "Choose a replacement or clear it" : words(key, choices[key])}))));
    const selected = rows.sleeves.find(row => row.id === choices.sleeves);
    const others = (selected?.used_by || []).filter(holder => holder.holder !== ed.id);
    sharing.hidden = shareControl.hidden = !others.length;
    sharing.textContent = others.length ? `This sleeves design is also used by ${others.map(holder => holder.title).join(", ")}.` : "";
    if (applyButton) applyButton.disabled = Object.values(choices).includes("__choose__") || !!others.length;
  }
  for (const key of KIT_FIELDS) {
    const value = choices[key], compatible = value == null || rows[key].some(row => row.id === value);
    const legacy = value && !known.has(value);
    if (!compatible && !legacy) choices[key] = "__choose__";
    const select = el("select", {id: `player-kit-${key}-${sheet.heading.id}`, "data-player-kit": key,
      onchange: event => {
        if (!current() || !event.currentTarget.isConnected || !body.contains(event.currentTarget)) return;
        choices[key] = event.currentTarget.value || null; drawReview();
      }},
    el("option", {value: "__choose__", text: "Choose a replacement or clear it", disabled: true}),
    el("option", {value: "", text: "None — clear this field"}),
    legacy ? el("option", {value, text: `Keep text: ${value}`}) : null,
    rows[key].map(row => {
      const taken = kitTaken(key, row);
      return el("option", {value: row.id, text: row.label, disabled: taken.taken && row.id !== value || null});
    }));
    select.value = choices[key] || ""; controls[key] = select;
    body.append(el("label", {class: "field", for: select.id}, el("span", {text: FIELD_WORDS[key]}), select),
      el("p", {class: "field-hint", text: `Now: ${kitName(key, ed.fields[key]) || "None"}.`}));
  }
  body.append(review, sharing, shareControl,
    el("p", {class: "sub", text: "This changes the local draft. Save the deck to record the player and kit together."}));
  sheetActions(sheet, [{text: "Use this player and kit", kind: "primary", onclick: event => {
    if (!current() || !event.currentTarget.isConnected || event.currentTarget !== applyButton || applyButton.disabled
        || !sheet.foot.contains(applyButton) || KIT_FIELDS.some(key => controls[key].value !== (choices[key] || ""))) return;
    const final = {player, ...choices};
    // Apply all three fields before changed() records history and persists/checks the draft.
    Object.assign(ed.fields, final); ed.playerKitItems = items;
    ed.playerKitRows = copiedPlayerKitRows(KIT_FIELDS.flatMap(field => items.some(item => item.kind === field && item.id === final[field])
      ? [{field, id: final[field]}] : []));
    sheet.close(); drawDetails(); changed({list: false});
    const again = ed.dom.page.querySelector(`[data-focus="field:player:${player}"]`);
    if (again) again.focus({preventScroll: true});
  }}, {text: "Keep editing", onclick: cancel}]);
  applyButton = sheet.foot.querySelector(".btn-primary");
  acceptedSharing.addEventListener("change", event => {
    if (!current() || event.currentTarget !== acceptedSharing || !acceptedSharing.isConnected || shareControl.hidden) return;
    applyButton.disabled = Object.values(choices).includes("__choose__") || !acceptedSharing.checked;
  });
  drawReview();
  return sheet;
}

/** Back from Built to a status that isn't: a line the file has though the deck isn't built is offered
 * only as Keep / Remove, so a value picked or typed while it was Built goes back to the file's. */
function resetStrayFields() {
  const ed = editor;
  for (const key of KIT_FIELDS) {
    if (strayKit(key) && ed.fields[key] !== null) ed.fields[key] = ed.base.fields[key];
  }
  if (strayBuiltVersion() && ed.fields.built_version !== null) ed.fields.built_version = ed.base.fields.built_version;
}

/** The closed "Deck details" line: "Idea · played by either · Bracket 2 · 1 change". */
function drawDetailsSummary() {
  const ed = editor;
  if (!ed.dom.detailsSummary) return;
  const f = ed.fields;
  const bits = [STATUS_WORDS[f.status] || "No status"];
  if (f.player) bits.push(`played by ${f.player === "either" ? "either" : playerWords(f.player)}`);
  if (ed.kind === "commander" && f.target_bracket) bits.push(`Bracket ${f.target_bracket}`);
  const n = Object.keys(changedFields()).length;
  ed.dom.detailsSummary.textContent = bits.join(" · ") + (n ? ` · ${plural(n, "change")}` : "");
}
