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
      host.append(choiceField("kind", "Format", [["casual", "Casual 60-card"], ["commander", "Commander"]]));
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
      "data-focus": `field:${key}:${value}`, onclick: () => setField(key, value) }, text));
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
  sleeves: { add: "+ Add new sleeves", stray: "The deck has a Sleeves line, but it isn't built: only a built deck has sleeves." },
  deck_box: { add: "+ Add a new deck box", stray: "The deck has a Deck box line, but it isn't built: only a built deck has one." },
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
  const id = `f-${key}`;
  const current = norm(key, ed.fields[key]);
  const rows = kitRows(key);
  // Older free text (the file's, or the draft's) stays pickable until something else is saved.
  const texts = [...new Set([ed.mode === "edit" ? norm(key, ed.base.fields[key]) : null, current])]
    .filter((v) => v && !rows.some((row) => row.id === v));
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
    others.length ? el("small", { class: "field-hint", text: `Other decks' sleeves: ${others.join(", ")}.` }) : null,
    ed.accLoad === "failed" ? el("small", { class: "field-hint field-problem", text: "The accessories list couldn't be loaded." }) : null);
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
  if (ed.mode !== "new" || ed.accRows || (ed.view && ed.view.accessories) || ed.accLoad) return;
  ed.accLoad = "loading";
  api("/api/accessories").then((data) => {
    if (editor !== ed) return;
    ed.accRows = kitRowsOf(data.items, accessoryOwnerOf(ed.fields.player));
    ed.accLoad = "done";
    redrawKitFields();
  }, () => {
    if (editor !== ed) return;
    ed.accLoad = "failed";
    redrawKitFields();
  });
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
  ed.fields[key] = value;
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
