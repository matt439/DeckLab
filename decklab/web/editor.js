/* Deck Lab's editor (Milestone 4; redesigned in UI-REVIEW.md WP11): change a deck's lists, header and
write-up, start new decks, and save.

The editor is eight scripts, loaded first and in this order, before matchups.js and the page's other
scripts (core.js, library.js, deck.js, stats.js, practice.js and app.js):
    editor.js           this file: the shared constants and the edit on screen (`editor`), lines and
                        lists, header fields, the write-up, re-applying changes onto a newer file, drafts,
                        undo history and the editor's keys, entering and leaving the editor, and sheets
                        (dialogs) and busy buttons
    editor-screen.js    drawing the editor: banners, the Cards and Notes tabs, the side panel (Add, Stats,
                        Checks), changed() and the bar
    editor-details.js   Deck details: the header fields, the Sleeves and Deck box pickers, setField()
    editor-lines.js     the list (dense rows or picture stacks): steppers, Remove and Undo, moving a line
    editor-cards.js     getting cards in: the Add panel's search and My collection, the Quick edit's search
                        sheet, a line's printing sheet, "Paste a list", a new deck's "Start from"
    editor-swaps.js     stand-ins for a missing card in the Play-now list, and their Substitutes notes
    editor-save.js      checking the draft and saving it
    editor-deckpage.js  the editor's parts on the deck page
They share one global scope with the page's other scripts (classic scripts), so a function in one
calls one in another as it is, once the page is running. The editor uses core.js's helpers (el, api,
apiWrite, state, ...), ui.js's openMenu and showToast, cards-ui.js's cardTile and pickPrinting, app.js's
route(), afterRender(), entryPos() and playerWords(), and deck.js's card helpers (typeGroup, copies,
manaCost, openCard, ...). app.js calls into this file from route() and the hashchange handler
(closeEditor, editorGuard, showEditor, showNewDeck, and on a phone showDesktopHandoff) and from "Switch"
(leaveEditor), and deck.js's deck page into editor-deckpage.js (deckActions, savedBox,
staleTableBox). matchups.js uses this file's ask(), busy() and unbusy().

Devices: the full editor from 600 px wide with any pointer (a tablet in portrait or landscape, a laptop,
a desktop), except a touch screen 500 px tall or less; a phone, upright or on its side, gets the Quick edit
(quickEditing: steppers, a search sheet with Paste, printings, deck details, Notes and Save).
New decks can be started on every screen size.

Routes:
    #/edit?id=<deck id>&v=target|owned   one list of a deck (the target list or the owned-only
                                         version) and the header fields, which go with either
    #/new[?kind=casual|commander]         a new deck from scratch
    #/new?from=<library id>               "Save as a new deck" from a product deck, a Beginner Box half
                                          or a pairing (those stay read-only)

What an edit holds (`editor`): the list being edited ({section: [line]}) and the header fields, next
to `base`, the same things as the file had them when the page loaded it, with its sha256. Lines keep
the file's order (a new one goes after the last card of its type, placeLine), so a save only moves
what changed; the page shows them grouped by section and type, like the deck page.

Drafts: every change is kept in localStorage per profile, deck and version when storage is available
("decklab.draft.<profile>.<deck id>.<version>", or ".new.<from or scratch>"), so a reload or a phone
going to sleep loses nothing; opening the editor again brings it back with a banner saying so. If the
file changed meanwhile, the draft's changes are re-applied to the latest version (rebase()).

Leaving with unsaved changes asks first: links and Back (editorGuard, which steps back through
history to the editor rather than writing over an entry), "Switch" (leaveEditor), and closing or
reloading the tab (beforeunload). If storage fails, a banner warns that the changes remain only in
the open editor, and leaving while keeping a draft or switching people is blocked.
*/
"use strict";

const DRAFT_DELAY = 250;        // ms after the last change before the draft is written
const MAX_COPIES = 99;          // copies on one line (the server's limit)
const MAX_TITLE = 100;          // characters in a new deck's title (the server's limit)
const EDIT_FIELDS = ["status", "player", "archetype", "built_version", "target_bracket", "sleeves", "deck_box"];
const NEW_FIELDS = ["title", "kind", "archetype", "player", "status", "target_bracket", "sleeves", "deck_box"];
const FIELD_WORDS = { title: "Title", kind: "Format", status: "Status", player: "Played by",
  archetype: "Archetype", built_version: "Built version", target_bracket: "Target bracket", sleeves: "Sleeves",
  deck_box: "Deck box", prose: "Write-up" };
// A built deck's kit: header lines holding an accessory id (the accessories, in the database) or older free text.
const KIT_FIELDS = ["sleeves", "deck_box"];
const KIND_WORDS = { casual: "60-card, 1v1", commander: "Commander (100 cards)" };
const OFFERED_SECTIONS = { casual: ["Deck", "Sideboard"], commander: ["Commander", "Deck", "Sideboard"] };
const SECTION_ORDER = ["Commander", "Companion", "Deck", "Sideboard"];
// Letters NFKD doesn't take apart, as decks.title_slug() writes them.
const SLUG_LETTERS = { "æ": "ae", "Æ": "Ae", "œ": "oe", "Œ": "Oe", "ø": "o", "Ø": "O", "ß": "ss", "ð": "d",
  "Ð": "D", "þ": "th", "Þ": "Th", "ł": "l", "Ł": "L" };
const SLUG_APOSTROPHES = /['\u2019\u2018\u02bc`\u00b4]/g;    // dropped from file names, as by decks.title_slug()
const PROSE_KEYS = ["substitutes", "notes"];      // the write-up's sections (api/drafts.py PROSE_SECTIONS)
const HISTORY_MAX = 100;        // changes Ctrl+Z can take back

let editor = null;              // the editor on screen, or null
let lineIds = 0;                // ids for lines on the page (never sent)
let sheetIds = 0;

/** The full editor: any screen from 600 px (a tablet in portrait or landscape, a laptop, a desktop), with a
 * mouse, a trackpad or a finger, but not a touch screen 500 px tall or less: a phone on its side (852 x 330)
 * would have two or three rows between the full editor's bars, and its search's results under the bottom
 * one. A short window with a mouse keeps the full editor. A phone gets the Quick edit (quickEditing). */
function canBuildDecks() {
  return window.matchMedia("(min-width: 600px)").matches
    && !window.matchMedia("(pointer: coarse) and (max-height: 500px)").matches;
}

/** A phone, upright or on its side: the editor is the Quick edit (compact rows with steppers, a search sheet,
 * printings, the status and Save; a new deck also has its title, format and "Start from"). An open editor
 * keeps its layout and draft when the screen turns, until the page is opened again. */
function quickEditing() { return !canBuildDecks(); }

/** app.js routes #/edit and #/new here on a phone: the same pages, in the Quick edit. */
function showDesktopHandoff(params) {
  if (params.get("id")) return showEditor(params, routeToken);
  return showNewDeck(params, routeToken);
}


// ------------------------------------------------------------ lines and lists

function newLine(raw) {
  return { uid: ++lineIds, qty: raw.qty, name: raw.name, set: raw.set || null, number: raw.number || null,
    finish: raw.finish || "nonfoil", card: raw.card || null };
}

/** Put a new line where a person would write it: after the section's last card of the same type (a
 * new instant goes with the instants, not after the basic lands; a new land before the basics), else
 * before the first card of a later type, else at the end. */
function placeLine(lines, line) {
  const order = (l) => TYPE_GROUPS.indexOf(typeGroup(l.card));
  const basic = (l) => Boolean(l.card && /\bBasic\b/.test(l.card.type_line));
  const mine = order(line);
  let at = -1;
  lines.forEach((l, i) => { if (order(l) === mine) at = i + 1; });
  if (at < 0) at = lines.findIndex((l) => order(l) > mine);
  if (at < 0) at = lines.length;
  while (at > 0 && !basic(line) && basic(lines[at - 1])) at -= 1;
  lines.splice(at, 0, line);
}

/** name|set|number|finish: lines with the same key are the same printing. */
function lineKey(line) {
  return [line.name, line.set || "", line.number || "", line.finish || "nonfoil"].join("|");
}

/** Fresh page lines (new ids) for {section: [line]}; empty sections are left out. */
function copyList(sections) {
  const out = {};
  for (const [name, lines] of Object.entries(sections || {})) {
    if (lines && lines.length) out[name] = lines.map(newLine);
  }
  return out;
}

/** A line as the server takes it: no card data, no page id. */
function sendLine(line) {
  const out = { qty: line.qty, name: line.name };
  if (line.set) {
    out.set = line.set;
    if (line.number) out.number = line.number;
  }
  if (line.finish && line.finish !== "nonfoil") out.finish = line.finish;
  return out;
}

function sendList(sections) {
  const out = {};
  for (const [name, lines] of Object.entries(sections)) if (lines.length) out[name] = lines.map(sendLine);
  return out;
}

/** The lines kept in a draft: as sent, plus their card data so the page can draw them at once. */
function keepList(sections) {
  const out = {};
  for (const [name, lines] of Object.entries(sections)) {
    if (lines.length) out[name] = lines.map((l) => ({ ...sendLine(l), card: l.card }));
  }
  return out;
}

function listSignature(sections) {
  return JSON.stringify(Object.keys(sections || {}).filter((n) => sections[n].length).sort()
    .map((n) => [n, sections[n].map((l) => [l.qty, lineKey(l)])]));
}

function sectionCount(sections, names) {
  return names.reduce((n, name) => n + copies((sections && sections[name]) || []), 0);
}

/** Cards that count towards the deck size: the Deck, and a Commander deck's commander. */
function mainCount(sections, kind) {
  return sectionCount(sections, kind === "commander" ? ["Commander", "Deck"] : ["Deck"]);
}

/** "FDN 227", "PLST E01-54 · foil", or "Any printing" for a line that names no set. */
function printingText(line) {
  if (!line || !line.set) return "Any printing";
  const finish = line.finish && line.finish !== "nonfoil" ? ` · ${line.finish}` : "";
  return `${line.set.toUpperCase()}${line.number ? ` ${line.number}` : ""}${finish}`;
}

/** "deck" (a Commander deck's "99"), "sideboard", "commander". */
function sectionWords(section) {
  if (section === "Deck") return editor && currentKind() === "commander" ? "99" : "deck";
  return section.toLowerCase();
}

/** {section: {key: {qty, line}}} summed over lines, for comparing lists printing by printing. */
function tally(sections) {
  const out = new Map();
  for (const [section, lines] of Object.entries(sections || {})) {
    for (const line of lines) {
      const key = `${section}\n${lineKey(line)}`;
      const had = out.get(key);
      if (had) had.qty += line.qty;
      else out.set(key, { section, qty: line.qty, line });
    }
  }
  return out;
}

/** What changed between two lists, card by card: [{section, name, before, after, from, to,
 * printing}]: copies before and after, the printings before and after ("FDN 227", or "2 FDN 227 +
 * 2 M19 314" for a card on more than one line), and whether the printings changed. */
function listChanges(base, now) {
  const cards = new Map();
  const note = (sections, side) => {
    for (const [section, lines] of Object.entries(sections || {})) {
      for (const line of lines) {
        const key = `${section}\n${line.name}`;
        if (!cards.has(key)) cards.set(key, { section, name: line.name, before: new Map(), after: new Map() });
        const seen = cards.get(key)[side];
        const p = printingText(line);
        seen.set(p, (seen.get(p) || 0) + line.qty);
      }
    }
  };
  note(base, "before");
  note(now, "after");
  const total = (m) => [...m.values()].reduce((a, b) => a + b, 0);
  const words = (m) => (m.size === 1 ? [...m.keys()][0] : [...m].map(([p, n]) => `${n} ${p}`).join(" + "));
  const out = [];
  for (const c of cards.values()) {
    const same = c.before.size === c.after.size && [...c.before].every(([p, n]) => c.after.get(p) === n);
    if (same) continue;
    const printings = c.before.size === c.after.size && [...c.before.keys()].every((p) => c.after.has(p));
    out.push({ section: c.section, name: c.name, before: total(c.before), after: total(c.after),
      from: c.before.size ? words(c.before) : null, to: c.after.size ? words(c.after) : null,
      printing: !printings && c.before.size > 0 && c.after.size > 0 });
  }
  const order = (c) => SECTION_ORDER.indexOf(c.section);
  return out.sort((a, b) => order(a) - order(b) || a.name.localeCompare(b.name));
}

function changeWords(c) {
  if (!c.before) return `Added ${c.after} ${c.name}` + (c.to !== "Any printing" ? ` (${c.to})` : "");
  if (!c.after) return `Removed ${c.before} ${c.name}`;
  if (c.printing && c.before === c.after) return `${c.name}: printing ${c.from} → ${c.to}`;
  return `${c.name}: ${c.before} → ${c.after}` + (c.printing ? ` (now ${c.to})` : "");
}

function changeKind(c) { return !c.before ? "added" : !c.after ? "removed" : "changed"; }

function findLine(uid) {
  for (const [section, lines] of Object.entries(editor.lists)) {
    const index = lines.findIndex((l) => l.uid === uid);
    if (index >= 0) return { line: lines[index], section, index };
  }
  return null;
}


// ----------------------------------------------------------------- fields

function pickFields(fields) {
  const f = fields || {};
  return { status: f.status || null, player: f.player || null, archetype: f.archetype || null,
    built_version: f.built_version || null, target_bracket: f.target_bracket || null, sleeves: f.sleeves || null,
    deck_box: f.deck_box || null };
}

function norm(key, value) {
  if (key === "archetype" || key === "title" || KIT_FIELDS.includes(key)) {
    const text = (value || "").trim().replace(/\s+/g, " ");
    return KIT_FIELDS.includes(key) && !text ? null : text;
  }
  return value == null || value === "" ? null : value;
}

function currentKind() { return editor.mode === "new" ? editor.fields.kind : editor.kind; }

/** True when the deck, as this save would leave it, has a target list and an owned-only version. */
function hasBothLists() {
  const ed = editor;
  if (ed.mode === "new") return false;
  return ed.version === "owned" ? ed.hasFileList || ed.starting : ed.view.lists.owned != null;
}

/** True when this edit takes a built deck apart (Status from Built to Building or Idea) and its text has
 * a Built version: the line goes too, since only a built deck has one (the server removes it as well). */
function builtVersionGoes() {
  const ed = editor;
  return ed.mode === "edit" && ed.base.fields.status === "built" && ed.fields.status !== "built"
    && ed.base.fields.built_version != null;
}

/** True when this edit takes a built deck apart and its text has a Sleeves (or, key "deck_box", Deck box)
 * line: it goes too, since the cards go back into storage unsleeved (the server removes it as well). */
function kitGo(key) {
  const ed = editor;
  return ed.mode === "edit" && ed.base.fields.status === "built" && ed.fields.status !== "built"
    && ed.base.fields[key] != null;
}

/** A Sleeves or Deck box line the deck's text has although the deck isn't built: the editor offers it only to
 * remove it. */
function strayKit(key) {
  const ed = editor;
  return ed.mode === "edit" && ed.base.fields.status !== "built" && ed.fields.status !== "built"
    && ed.base.fields[key] != null;
}

/** A Built version the deck's text has although the deck isn't built (written by hand): the editor offers it
 * only to remove it. */
function strayBuiltVersion() {
  const ed = editor;
  return ed.mode === "edit" && ed.base.fields.status !== "built" && ed.fields.status !== "built"
    && ed.base.fields.built_version != null;
}

/** Whether the editor offers a header field now (it follows the status and the lists). */
function fieldOffered(key) {
  const ed = editor;
  // Sleeves and deck boxes are home's (the accessories): a person's deck has none, unless its text has one.
  // Nor are they shown to a person-space profile (mayDo("see_accessories")); the server leaves them out too.
  if (KIT_FIELDS.includes(key)) {
    if (!mayDo("see_accessories")) return false;
    return (ed.fields.status === "built" && (!ed.space || ed.space === HOME_SPACE)) || strayKit(key);
  }
  if (ed.mode === "new") return key !== "built_version" && (key !== "target_bracket" || ed.fields.kind === "commander");
  if (key === "built_version") return (ed.fields.status === "built" && hasBothLists()) || strayBuiltVersion();
  if (key === "target_bracket") return ed.kind === "commander";
  return EDIT_FIELDS.includes(key);
}

/** The header fields that differ from the saved deck ({key: value}), as a save sends them. */
function changedFields() {
  const out = {};
  for (const key of EDIT_FIELDS) {
    if (!fieldOffered(key)) {
      if (key === "built_version" && builtVersionGoes()) out.built_version = null;
      if (KIT_FIELDS.includes(key) && kitGo(key)) out[key] = null;
      continue;
    }
    const now = norm(key, editor.fields[key]);
    if (now !== norm(key, editor.base.fields[key])) out[key] = now;
  }
  return out;
}

/** "Built version: owned-only version → removed (only a built deck has one)": a header change in words. */
function fieldChangeWords(key, value) {
  const was = fieldValueWords(key, editor.base.fields[key]);
  if (value == null && editor.base.fields[key] != null) {
    // Only when the line goes because the deck isn't (or won't be) built: None picked on a deck that
    // stays built, or a Built version cleared because the deck has one list now, is simply removed.
    const unbuilt = key === "built_version" ? builtVersionGoes() || strayBuiltVersion()
      : KIT_FIELDS.includes(key) && (kitGo(key) || strayKit(key));
    return `${FIELD_WORDS[key]}: ${was} → removed` + (unbuilt ? " (only a built deck has one)" : "");
  }
  return `${FIELD_WORDS[key]}: ${was} → ${fieldValueWords(key, value)}`;
}

/** A new deck's fields as /api/decks takes them. */
function newDeckFields() {
  const f = editor.fields;
  // A person's deck has no Played by.
  const home = !editor.space || editor.space === HOME_SPACE;
  const out = home && f.player ? { player: f.player, status: f.status } : { status: f.status };
  const archetype = norm("archetype", f.archetype);
  if (archetype) out.archetype = archetype;
  if (f.kind === "commander" && f.target_bracket) out.target_bracket = f.target_bracket;
  for (const key of KIT_FIELDS) {
    const value = norm(key, f[key]);
    if (f.status === "built" && value) out[key] = value;
  }
  return out;
}

function listChanged() {
  return editor.starting || listSignature(editor.lists) !== listSignature(editor.base.lists);
}

function isDirty() {
  const ed = editor;
  if (!ed) return false;
  if (ed.mode === "new") {
    return listSignature(ed.lists) !== listSignature(ed.base.lists)
      || NEW_FIELDS.some((k) => norm(k, ed.fields[k]) !== norm(k, ed.base.fields[k]));
  }
  return listChanged() || Object.keys(changedFields()).length > 0 || Object.keys(changedProse()).length > 0
    || !!ed.markCurrent;
}

/** The write-up's sections that differ from the saved deck ({key: text}), as a save sends them. */
function changedProse() {
  const ed = editor;
  const out = {};
  if (!ed || ed.mode !== "edit" || !ed.prose) return out;
  for (const key of PROSE_KEYS) {
    const now = (ed.prose[key] || "").replace(/\r\n?/g, "\n").replace(/^\n+|\n+$/g, "");
    const was = (ed.base.prose && ed.base.prose[key]) || "";
    if (now !== was) out[key] = now;
  }
  return out;
}

/** The saved deck's write-up, from an edit view ({substitutes, notes}, "" for a section it hasn't). */
function proseOf(view) {
  const p = (view && view.prose) || {};
  return Object.fromEntries(PROSE_KEYS.map((key) => [key, p[key] || ""]));
}

function bracketWords(n) {
  const b = (editor && editor.brackets || []).find((x) => x.number === n);
  return b ? `${n} (${b.name})` : `Bracket ${n}`;
}

function fieldValueWords(key, value) {
  if (value == null || value === "") return "not set";
  if (key === "status") return STATUS_WORDS[value] || value;
  if (key === "player") return value === "either" ? "either of you" : playerWords(value);
  if (key === "built_version") return listName(value === "owned" ? "owned" : "target", true);
  if (key === "target_bracket") return bracketWords(value);
  if (key === "kind") return KIND_WORDS[value] || value;
  const row = KIT_FIELDS.includes(key) ? kitRow(key, value) : null;
  return row ? row.label : `“${value}”`;
}


// ----------------------------------------------------------------- the kit

/** The accessories the Sleeves (or Deck box) picker offers: [{id, label, colour, quantity, image_url,
 * used_by: [{holder, title, kind, need}]}], from /api/deck/edit's "accessories", or from the accessories
 * list loaded since (after a row is added here, or for a new deck from scratch, which has no edit view). */
function kitRows(key) {
  const ed = editor;
  const rows = ed.accRows || (ed.view && ed.view.accessories) || {};
  return rows[key] || [];
}

/** /api/accessories's items as kitRows has them ({sleeves: [...], deck_box: [...]}): only those a deck of
 * owner may take (accessoryUsable: its owner's or shared). */
function kitRowsOf(items, owner) {
  const out = Object.fromEntries(KIT_FIELDS.map((key) => [key, []]));
  for (const item of items || []) {
    if (item.editable !== false && out[item.kind] && accessoryUsable(item, owner)) {
      out[item.kind].push({ id: item.id, label: item.label, colour: item.colour || null, quantity: item.quantity,
        capacity: item.capacity == null ? null : item.capacity, image_url: item.image_url || null, used_by: item.used_by || [] });
    }
  }
  return out;
}

/** The accessories-list row a Sleeves or Deck box value names, or null (blank, or older free text). */
function kitRow(key, value) {
  const id = norm(key, value);
  return id ? kitRows(key).find((row) => row.id === id) || null : null;
}

/** How a Sleeves or Deck box value reads: the row's name, the free text as written, or null. */
function kitName(key, value) {
  const row = kitRow(key, value);
  return row ? row.label : norm(key, value);
}

/** A row's other holders ([{holder, title, ...}]) and whether that makes it taken for this deck: sleeves
 * never (one design may sleeve several decks; it's up to the players not to play two of them at once), a
 * deck box by as many holders as there are boxes. */
function kitTaken(key, row) {
  const ed = editor;
  const others = (row.used_by || []).filter((h) => ed.mode !== "edit" || h.holder !== ed.id);
  const none = key === "deck_box" && Number(row.quantity) === 0;     // no box to put the deck in
  return { others, none, taken: key === "sleeves" ? false : none || others.length >= row.quantity };
}

/** The sleeves the deck needs as this save would leave it: every card (sideboard and basics included) of
 * its built list, the Built version's or, without one, the owned-only version's when there is one
 * (drafts._built_sections' rule). */
function kitNeed() {
  const ed = editor;
  if (ed.mode === "edit" && ed.fields.status === "built" && Number.isInteger(ed.view?.assembled_need)) {
    return ed.view.assembled_need;
  }
  let lists = ed.lists || {};
  if (ed.mode === "edit") {
    const version = ed.fields.built_version || (hasBothLists() ? "owned" : "target");
    if (version !== ed.version) lists = (ed.view.lists && ed.view.lists[version]) || {};
  }
  return Object.values(lists).reduce((n, lines) => n + (lines || []).reduce((m, l) => m + (l.qty || 0), 0), 0);
}

/** "lorien-elves" for "Lórien Elves", as decks.title_slug() makes it (the server has the last word). */
function slugOf(title) {
  // Apostrophes go (a possessive stays one word, typed on a phone or the PC), accents and invisible
  // characters go, and anything else that isn't an ASCII letter or digit separates words.
  const text = [...String(title)].map((ch) => SLUG_LETTERS[ch] || ch).join("").replace(SLUG_APOSTROPHES, "")
    .normalize("NFKD").replace(SLUG_APOSTROPHES, "").replace(/[\p{Mn}\p{Cf}]/gu, "");
  return text.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 60).replace(/-+$/, "");
}

/** Why a new deck's title can't be used yet, or null. */
function titleProblem() {
  const title = norm("title", editor.fields.title);
  if (!title) return "Give the deck a title: it becomes the deck's id too.";
  if (title.length > MAX_TITLE) return `The title can be at most ${MAX_TITLE} characters.`;
  const slug = slugOf(title);
  if (!slug) return "The title needs some letters or digits for the deck's id.";
  // A deck's slug is taken by a deck of either kind in the same space (home ids: <kind>/<slug>; a person's:
  // <space>/<kind>/<slug>).
  const space = editor.space || HOME_SPACE;
  const taken = state.library && state.library.decks.find((d) => {
    const parts = d.id.split("/");
    const [kind, rest] = space === HOME_SPACE ? [parts[0], parts[1]] : parts[0] === space ? [parts[1], parts[2]] : [null, null];
    return (kind === "casual" || kind === "commander") && String(rest).toLowerCase() === slug;
  });
  if (taken) return `There's already a deck called ${slug} (${taken.title}): pick another title.`;
  // The source's own suggestion, which /api/deck/edit checked (the library may not have come yet).
  const source = editor.view && editor.view.new_deck;
  if (source && source.exists && source.slug === slug) return `There's already a deck called ${slug}: pick another title.`;
  return null;
}

/** The title's problem once something has been typed (an empty title isn't a problem to shout about). */
function typedTitleProblem() {
  return editor.mode === "new" && norm("title", editor.fields.title) ? titleProblem() : null;
}


// --------------------------------------------------------------- re-applying

/** latest with the changes from base to mine on top: each printing's copies go up or down by what
 * changed here (a card added here that the latest version lacks is added). A printing the latest
 * version changed too gets a note, as does a take-out that can't be made in full. {lists, notes}. */
function reapplyList(base, mine, latest) {
  const result = copyList(latest);
  const before = tally(base);
  const after = tally(mine);
  const theirs = tally(latest);
  const notes = [];
  for (const key of new Set([...before.keys(), ...after.keys()])) {
    const b = before.get(key);
    const a = after.get(key);
    const delta = (a ? a.qty : 0) - (b ? b.qty : 0);
    if (!delta) continue;
    const { section, line } = a || b;
    const was = b ? b.qty : 0;
    const now = theirs.has(key) ? theirs.get(key).qty : 0;
    const lines = result[section] || (result[section] = []);
    const same = lines.filter((l) => lineKey(l) === lineKey(line));
    const where = `${line.name} (${printingText(line)}${section === "Deck" ? "" : `, ${sectionWords(section)}`})`;
    let take = 0;
    if (delta > 0) {
      if (same.length) same[0].qty = Math.min(MAX_COPIES, same[0].qty + delta);
      else placeLine(lines, newLine({ ...line, qty: Math.min(MAX_COPIES, delta) }));
    } else {
      take = -delta;
      for (const l of same) {
        const n = Math.min(take, l.qty);
        l.qty -= n;
        take -= n;
      }
      if (take > 0) {
        notes.push(`${where}: you took out ${-delta}, but the latest version had ` +
          `${-delta - take === 0 ? "none" : `only ${-delta - take}`} of it.`);
      }
      result[section] = lines.filter((l) => l.qty > 0);
    }
    if (!take && now !== was) {
      // Both changed this printing: say what the sum came to, so it isn't a surprise in the review.
      const total = copies((result[section] || []).filter((l) => lineKey(l) === lineKey(line)));
      notes.push(`${where}: the latest version has ${now} (${was || "none"} when you opened it); with your ` +
        `${delta > 0 ? "+" : "−"}${Math.abs(delta)} it's ${total ? total : "taken out"} now.`);
    }
  }
  for (const name of Object.keys(result)) if (!result[name].length) delete result[name];
  return { lists: result, notes };
}

/** latest's fields with the ones changed here (from base to mine) put back. {fields, notes}. */
function reapplyFields(base, mine, latest) {
  const fields = { ...latest };
  const notes = [];
  for (const key of EDIT_FIELDS) {
    if (norm(key, mine[key]) === norm(key, base[key])) continue;
    if (norm(key, latest[key]) !== norm(key, base[key]) && norm(key, latest[key]) !== norm(key, mine[key])) {
      notes.push(`${FIELD_WORDS[key]}: the latest version says ${fieldValueWords(key, latest[key])}; ` +
        `yours, ${fieldValueWords(key, mine[key])}, is kept.`);
    }
    fields[key] = mine[key];
  }
  return { fields, notes };
}

/** Make view (the latest /api/deck/edit answer) the editor's file, with mine's changes from base
 * re-applied on top. Returns notes about anything that couldn't be re-applied exactly. */
function rebase(ed, view, mine, base) {
  const latest = view.lists[ed.version];
  let lists;
  let notes = [];
  let starting = false;
  if (mine.starting) {
    // An owned-only version started here: it's all new, so it stays as it is.
    lists = copyList(mine.lists);
    starting = latest == null;
    if (!starting) notes.push(`The latest version already has a ${listName("owned", true)}: saving replaces it with this one.`);
  } else {
    ({ lists, notes } = reapplyList(base.lists, mine.lists, latest || {}));
  }
  const latestFields = pickFields(view.fields);
  const f = reapplyFields(pickFields(base.fields), { ...latestFields, ...mine.fields }, latestFields);
  // The write-up: a section changed here keeps this text (the latest version's change to it is named).
  const latestProse = proseOf(view);
  const prose = { ...latestProse };
  for (const key of PROSE_KEYS) {
    const was = (base.prose || {})[key] || "";
    const now = (mine.prose || {})[key];
    if (now == null || now === was) continue;
    if (latestProse[key] !== was && latestProse[key] !== now) {
      notes.push(`The ${key === "notes" ? "Notes" : "Substitutes"} write-up changed in the latest version too; yours is kept.`);
    }
    prose[key] = now;
  }
  Object.assign(ed, {
    view, sha256: view.sha256, title: view.title, kind: view.kind, sections: view.sections,
    brackets: view.brackets || [], hasFileList: latest != null, starting,
    base: { lists: copyList(latest || {}), fields: latestFields, prose: latestProse },
    lists, fields: f.fields, removed: [], accRows: null, prose, markCurrent: !!(mine.markCurrent && view.changed_on),
  });
  return [...notes, ...f.notes];
}


// ------------------------------------------------------------------ drafts

function draftKey(ed) {
  const where = ed.space && ed.space !== HOME_SPACE ? `${ed.space}.` : "";
  return ed.mode === "new" ? `draft.${ed.profile}.new.${where}${ed.from || "scratch"}` : `draft.${ed.profile}.${ed.id}.${ed.version}`;
}

function queueDraft() {
  clearTimeout(editor.draftTimer);
  const ed = editor;
  // Undoing the final change must clear its earlier draft before clean navigation can proceed.
  if (!isDirty()) { saveDraft(ed); return; }
  editor.draftTimer = setTimeout(() => saveDraft(ed), DRAFT_DELAY);
}

/** Keep the changes on this device; false means the current work is only safe in this open editor. */
function saveDraft(ed) {
  if (!ed || ed !== editor) return false;
  if (ed.leaving) return true;
  clearTimeout(ed.draftTimer);
  if (ed.pendingDraftKey && !removeDraft(ed)) return false;
  if (!isDirty()) {
    const removed = removeDraft(ed);
    if (removed) draftStored(ed, true);
    return removed;
  }
  const saved = local.set(draftKey(ed), JSON.stringify({
    v: 1, saved: Date.now(), sha256: ed.sha256 || null, starting: !!ed.starting,
    base: { lists: sendList(ed.base.lists), fields: ed.base.fields, prose: ed.base.prose || null },
    lists: keepList(ed.lists), fields: ed.fields, addSection: ed.addSection,
    prose: ed.prose || null, markCurrent: !!ed.markCurrent }));
  draftStored(ed, saved);
  return saved;
}

function draftStored(ed, saved) {
  const failed = !saved;
  if (!!ed.draftFailed === failed && !(saved && ed.draftRemoveFailed)) return;
  ed.draftFailed = failed;
  if (saved) ed.draftRemoveFailed = false;
  if (ed === editor && ed.dom && ed.dom.banners) drawBanners();
}

function readDraft(ed) {
  try {
    const draft = JSON.parse(local.get(draftKey(ed)) || "null");
    return draft && draft.v === 1 && draft.lists && draft.fields && draft.base ? draft : null;
  } catch (e) {
    return null;
  }
}

function removeDraft(ed) {
  const keys = new Set([draftKey(ed), ed.pendingDraftKey].filter(Boolean));
  const removed = [...keys].map(key => local.remove(key)).every(Boolean);
  if (removed) ed.pendingDraftKey = null;
  if (!!ed.draftRemoveFailed !== !removed) {
    ed.draftRemoveFailed = !removed;
    if (ed === editor && ed.dom && ed.dom.banners) drawBanners();
  }
  return removed;
}

/** "2:31 pm today", "9:05 am yesterday" or "28 Sep, 2:31 pm". */
function timeWords(ms) {
  const d = new Date(ms);
  const clock = d.toLocaleTimeString("en-AU", { hour: "numeric", minute: "2-digit" }).replace(/\s/g, " ");
  const day = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((day(new Date()) - day(d)) / 86400000);
  if (days === 0) return `${clock} today`;
  if (days === 1) return `${clock} yesterday`;
  return `${d.getDate()} ${d.toLocaleDateString("en-AU", { month: "short" })}, ${clock}`;
}


// ------------------------------------------------------ entering and leaving

function editHref(id, version) {
  return `#/edit?id=${encodeURIComponent(id)}&v=${version === "owned" ? "owned" : "target"}`;
}

function showEditor(params, token) {
  if (params.get("revision")) return showRevisionEditor(params, token);
  let id = params.get("id");
  if (id.startsWith("pairing/")) id = id.replace(/ /g, "+");       // a "+" typed in the address bar
  const version = params.get("v") === "owned" ? "owned" : "target";
  setTitle("Edit deck");
  load(`/api/deck/edit?id=${encodeURIComponent(id)}`, token, (view) => {
    if (typeof boxEditorGuardView === "function" && !boxEditorGuardView(view, version, token)) return;
    canonicalDeckAddress(view.id);
    if (!view.editable && view.new_deck) {
      // A product deck or pairing is never edited in place: it's saved as a new deck.
      history.replaceState(history.state, "", `#/new?from=${encodeURIComponent(view.id)}`);
      startEditor({ mode: "new", view, from: view.id, space: params.get("space") });
      return;
    }
    if (!view.editable) {
      $("#main").append(el("nav", { class: "crumbs", "aria-label": "Breadcrumb" },
        el("a", { href: deckHref(view.id, version), text: `← ${view.title}` })),
      el("div", { class: "box box-warn" }, el("h1", { text: `${view.title} can't be edited here` }),
        el("p", { text: view.why_not })));
      return;
    }
    openSavedDeckEditor(view, version);
    openSwapsFromRoute(params, view.id);      // editor-swaps.js: the deck page's swap= and tab=notes
  });
}

function showNewDeck(params, token) {
  const from = params.get("from");
  setTitle("New deck");
  // The library says which titles are taken (someone may have made a deck since it was last read);
  // the title's hint and the bar are drawn again when it comes.
  api("/api/decks").then((data) => {
    state.library = data;
    if (editor && editor.mode === "new" && editor.dom) {
      drawTitleHint();
      drawBar();
      drawCheck();
    }
  }).catch(() => {});
  if (from) {
    load(`/api/deck/edit?id=${encodeURIComponent(from)}`, token, (view) => {
      if (view.editable) {
        // A deck of your own is edited in place; "Save as a new deck" is for read-only decks.
        history.replaceState(history.state, "", editHref(view.id, "target"));
        startEditor({ mode: "edit", view, version: "target" });
        return;
      }
      startEditor({ mode: "new", view, from: view.id, space: params.get("space") });
    });
    return;
  }
  const kind = params.get("kind") === "commander" ? "commander" : "casual";
  clear($("#main"));
  startEditor({ mode: "new", kind, space: params.get("space") });
  afterRender();
}

function startEditor(opts) {
  disposeEditorSearchDock(editor, { takeover: true });
  const profile = state.profile;
  const ed = { mode: opts.mode, version: opts.version || "target", profile: profile.id, checkSeq: 0, check: null, checkError: null,
    notice: null, lastAdded: null, flash: null, addSection: "Deck", leaving: false, asking: false,
    brackets: [], sent: {}, removed: [], pos: entryPos(), entryHash: location.hash, entryToken: routeToken,
    pendingDraftKey: opts.pendingDraftKey || null,
    draftRemoveFailed: !!opts.pendingDraftKey, quick: quickEditing(), history: [], snap: null,
    side: local.get("editSide") || "add", look: local.get("editLook") === "visual" ? "visual" : "list",
    tab: "cards", prose: null, markCurrent: false };
  if (opts.mode === "edit") {
    const view = opts.view;
    const fileList = view.lists[ed.version];
    Object.assign(ed, { id: view.id, kind: view.kind, title: view.title, view, sha256: view.sha256,
      sections: view.sections, brackets: view.brackets || [], hasFileList: fileList != null, starting: false,
      base: { lists: copyList(fileList || {}), fields: pickFields(view.fields), prose: proseOf(view) } });
    ed.space = view.space || deckSpaceOf(view.id);
    // Someone else's deck: its changes can be tried and tested, not saved (Save is hidden).
    ed.readOnly = view.may_save === false
      || !canEditDeck({ id: view.id, space: ed.space, player: view.fields && view.fields.player });
  } else {
    const view = opts.view || null;
    const source = view && view.new_deck;
    const kind = source ? source.kind : opts.kind;
    Object.assign(ed, { id: null, from: opts.from || null, view, kind, title: "", sha256: null,
      brackets: (view && view.brackets) || [], hasFileList: false, starting: false,
      sections: view ? view.sections : OFFERED_SECTIONS[kind],
      base: { lists: copyList(view ? view.lists.target : {}),
        fields: { title: source ? source.title : "", kind, archetype: "", player: null,
          status: "idea", target_bracket: 2, sleeves: "", deck_box: "" } } });
    ed.space = newDeckSpace(opts.space);
    ed.base.fields.player = newDeckPlayer(ed.space);
    ed.readOnly = false;
  }
  ed.lists = copyList(ed.base.lists);
  ed.fields = { ...ed.base.fields };
  if (ed.base.prose) ed.prose = { ...ed.base.prose };
  editor = ed;
  const draft = opts.restoreDraft === false ? null : readDraft(ed);
  if (draft) {
    const mine = { lists: draft.lists, fields: draft.fields, starting: draft.starting, prose: draft.prose,
      markCurrent: draft.markCurrent };
    if (ed.mode === "edit" && draft.sha256 !== ed.sha256) {
      const notes = rebase(ed, ed.view, mine, draft.base);
      ed.notice = { kind: "draft-changed", saved: draft.saved, notes };
    } else {
      ed.lists = copyList(draft.lists);
      ed.fields = { ...ed.fields, ...draft.fields };
      if (ed.prose && draft.prose) ed.prose = { ...ed.prose, ...draft.prose };
      ed.markCurrent = !!(draft.markCurrent && ed.view && ed.view.changed_on);
      ed.starting = !!draft.starting && ed.mode === "edit" && !ed.hasFileList;
      ed.notice = { kind: "draft", saved: draft.saved };
    }
    if (draft.addSection) ed.addSection = draft.addSection;
  }
  if (typeof attachBoxEditorContext === "function") attachBoxEditorContext(ed);
  syncSections();
  ed.dirty = isDirty();
  ed.snap = snapshot(ed);
  drawEditor();
  scheduleCheck(0);
}

/** Where a new deck goes: the space asked for when the visitor may add decks there, else their own
 * space if they may, else the first place they may. */
function newDeckSpace(wanted) {
  const targets = createTargets();
  if (wanted && targets.some((t) => t.space === wanted)) return wanted;
  const own = targets.find((t) => t.space === ownSpace());
  return own ? own.space : targets.length ? targets[0].space : HOME_SPACE;
}

/** A new deck's Played by in a space: none in a person's space; at home the one the visitor must use
 * (a member's own), else theirs, else "either". */
function newDeckPlayer(space) {
  if (space !== HOME_SPACE) return null;
  const target = createTargets().find((t) => t.space === HOME_SPACE && t.player);
  return target ? target.player : (state.profile.plays_as || "either");
}

/** The Played by choices the visitor may pick at home: just their own for a member (lib/permissions.py). */
function allowedPlayers() {
  const all = [["user", playerWords("user")], ["wife", playerWords("wife")], ["either", "Either"]];
  const may = state.may;
  if (!may || may.admin || !may.home_player || (editor && editor.readOnly)) return all;
  return all.filter(([value]) => value === may.home_player);
}

/** The sections on offer: the kind's, plus any the list has. The Add-to choice stays one of them. */
function syncSections() {
  const ed = editor;
  const offered = new Set([...(ed.mode === "new" && !ed.from ? OFFERED_SECTIONS[ed.fields.kind] : ed.sections),
    ...Object.keys(ed.lists).filter((s) => ed.lists[s].length)]);
  ed.sections = SECTION_ORDER.filter((s) => offered.has(s));
  if (!ed.sections.includes(ed.addSection)) ed.addSection = "Deck";
}

/** The page is leaving the editor (app.js's route()): keep its draft, stop its timers. */
function closeEditor() {
  if (state.saved && state.saved.hash !== location.hash) state.saved = null;
  if (!editor) return;
  const ed = editor;
  saveDraft(ed);
  disposeEditorSearchDock(ed);
  clearTimeout(ed.checkTimer);
  clearTimeout(ed.draftTimer);
  cancelEditorSearch(ed.ac);
  document.body.classList.remove("is-searching", "keyboard-up", "has-edit-bar", "is-quick-edit");
  editor = null;
}

function editorDirty() { return !!(editor && !editor.leaving && (isDirty() || editor.draftRemoveFailed)); }

/** app.js's hashchange handler asks this first. With unsaved changes it puts the editor's address
 * back, asks, and goes on to the new one only if the person says so. True when it has taken over. */
function editorGuard(oldHash, newHash) {
  const ed = editor;
  if (!ed) return false;
  if (ed.undo && location.hash === ed.undo.hash) {
    // The step back to the editor that stepBack() asked for: nothing to route.
    ed.undo.done();
    ed.undo = null;
    return true;
  }
  if (ed.leaving) return false;
  if (!ed.asking && !editorDirty()) return false;
  const redo = stepBack(ed, oldHash);
  if (ed.asking) return true;          // already asking: the answer given there counts
  const back = ed.undo ? ed.undo.promise : Promise.resolve();
  confirmLeave().then(async (leave) => {
    if (!leave) return;
    // The browser may still be on its way back to the editor's entry; go on from there.
    await Promise.race([back, new Promise((resolve) => setTimeout(resolve, 1500))]);
    if (redo) {
      history.go(redo);
    } else {
      history.replaceState(history.state, "", newHash);
      route();
    }
  });
  return true;
}

/** Put the editor's address back after the browser moved off it, by going the other way through
 * history (Forward after Back, Back after a link) instead of writing over an entry, so the entries
 * around the editor stay as they were (a second Back still reaches the deck page). Returns the
 * steps that make the same move again, or 0 when history can't tell where the editor's entry is
 * (the address is then put back in place). */
function stepBack(ed, oldHash) {
  const here = entryPos();
  const steps = ed.pos == null ? 0 : ed.pos - here;
  if (!steps) {
    history.replaceState(history.state, "", oldHash);
    return 0;
  }
  let done;
  const promise = new Promise((resolve) => { done = resolve; });
  ed.undo = { hash: oldHash, done, promise };
  history.go(steps);
  return -steps;
}

/** "Switch" and the like: true when it's all right to leave the editor (asking first if needed).
 * ask false keeps unsaved changes as a draft without asking. */
async function leaveEditor(ask = true) {
  if (!editorDirty()) return true;
  if (!ask) {
    if (!saveDraft(editor)) {
      toast("This browser couldn't keep your changes. Save the deck before switching people; the editor is still open.");
      return false;
    }
    editor.leaving = true;
    disposeEditorSearchDock(editor);
    document.querySelectorAll("dialog.sheet").forEach((d) => d.close());   // a question left open, too
    return true;
  }
  if (editor.asking) return false;
  return confirmLeave();
}

async function confirmLeave() {
  const ed = editor;
  const kept = saveDraft(ed);
  ed.asking = true;
  const what = ed.mode === "new" ? "the new deck" : `${ed.title}'s ${listName(ed.version, true)}`;
  const choice = await ask("Leave without saving?", [
    ed.pendingDraftKey ? "The deck is saved on the PC, but its old draft still needs to be removed from this device."
      : `Your changes to ${what} aren't saved yet.`,
    kept ? "If you leave, they're kept on this device, for you only, and come back when you open the editor again."
      : "This browser couldn't keep a draft. Your changes are only in this open editor: keep editing and save the deck, or discard them."],
  [{ value: "stay", text: "Keep editing", kind: "primary" },
    ...(kept ? [{ value: "leave", text: "Leave, and keep them for later" }] : []),
    { value: "discard", text: "Discard them and leave", kind: "danger" }],
  // Asked while the browser steps back to the editor's entry (editorGuard): no entry of its own on top.
  { history: false });
  ed.asking = false;
  if (editor !== ed || ed.leaving) return false;     // the page moved on meanwhile: nothing more to do
  if (choice === "leave" && !saveDraft(ed)) {
    toast("This browser couldn't keep your latest changes. The editor is still open: save the deck before leaving.");
    return false;
  }
  if (choice === "discard" && !removeDraft(ed)) {
    toast("This browser couldn't remove the stored draft. The editor is still open; try again when storage is available.");
    return false;
  }
  if (choice === "leave" || choice === "discard") {
    ed.leaving = true;
    return true;
  }
  return false;
}

window.addEventListener("beforeunload", (event) => {
  if (!editorDirty()) return;
  saveDraft(editor);
  event.preventDefault();
  event.returnValue = "";         // older browsers need this to ask
});
window.addEventListener("pagehide", () => { if (editor) saveDraft(editor); });
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden" && editor) saveDraft(editor);
});


// ------------------------------------------------------------- undo history

/** What Ctrl+Z goes back to: the lists, the header fields, the Add-to section and the write-up, as text. */
function snapshot(ed) {
  return JSON.stringify({ lists: keepList(ed.lists), fields: ed.fields, addSection: ed.addSection,
    prose: ed.prose, markCurrent: !!ed.markCurrent, starting: !!ed.starting });
}

/** After a change (editor-screen.js changed()): the state before it goes on the history. */
function recordHistory(ed = editor) {
  const now = snapshot(ed);
  if (ed.snap != null && now !== ed.snap) {
    ed.history.push(ed.snap);
    if (ed.history.length > HISTORY_MAX) ed.history.shift();
  }
  ed.snap = now;
}

/** Ctrl+Z: back to the state before the last change. False when there's nothing to undo. */
function undoLast() {
  const ed = editor;
  if (!editorKeyboardCurrent(ed) || ed.saving || ed.asking || ed.leaving || !ed.history?.length
    || document.querySelector("dialog[open]") || keyboardMenuOpen()) return false;
  const focus = editorUndoFocus(ed);
  const was = JSON.parse(ed.history.pop());
  ed.lists = copyList(was.lists);
  ed.fields = was.fields;
  ed.addSection = was.addSection || "Deck";
  if (was.prose) ed.prose = was.prose;
  ed.markCurrent = !!was.markCurrent;
  ed.starting = !!was.starting;
  ed.removed = [];            // their own Undo would put a card back twice
  ed.lastAdded = null;
  ed.snap = snapshot(ed);
  syncSections();
  drawEditor();
  changed({ list: false, history: false });
  restoreEditorUndoFocus(ed, focus);
  return true;
}

/** The mounted Editor page and person still own these controls. */
function editorKeyboardCurrent(ed = editor) {
  const own = ed?.dom?.keyboardOwner;
  return !!(ed === editor && own && own.page === ed.dom.page && own.page.isConnected
    && own.token === routeToken && own.profile === ed.profile && own.profile === state.profile?.id);
}

/** An earlier handler, IME composition or AltGraph owns this event. Binding modifiers stay local. */
function editorKeyIgnored(event) {
  return !!(event.defaultPrevented || event.isComposing || event.keyCode === 229
    || event.getModifierState?.("AltGraph") || event.target?.editorComposing);
}

/** Intermediate composed text is not a quantity or an Add intent. Process the finished text once. */
function editorComposition(input, update) {
  input.addEventListener("compositionstart", (event) => { input.editorComposing = true; update(event); });
  input.addEventListener("compositionend", (event) => { input.editorComposing = false; update(event); });
}

/** True when a key went to a box being typed in (it has its own Ctrl+Z, and "/" is a character there). */
function typingIn(target) { return keyboardEditing(target); }

/** The editor's keys: Ctrl/Cmd+S saves, Ctrl/Cmd+Z takes back the last change, "/" goes to the search. */
function editorKeys(e) {
  const ed = editor;
  if (!editorKeyboardCurrent(ed) || editorKeyIgnored(e)) return;
  const mod = Boolean(e.ctrlKey) !== Boolean(e.metaKey), key = (e.key || "").toLowerCase();
  const exact = mod && !e.altKey && !e.shiftKey, save = exact && key === "s", undo = exact && key === "z";
  if (document.querySelector("dialog[open]") || keyboardMenuOpen() || ed.saving || ed.asking || ed.leaving) {
    if (save || (undo && !typingIn(e.target) && !document.querySelector("dialog[open]") && !keyboardMenuOpen())) e.preventDefault();
    return;
  }
  if (save) {
    e.preventDefault();
    if (!e.repeat && !ed.readOnly) saveNow();
  } else if (undo && !typingIn(e.target)) {
    if (e.repeat) { e.preventDefault(); return; }
    if (undoLast()) { e.preventDefault(); toast("Undone."); }
  } else if (e.key === "/" && keyboardCharactersEnabled(ed.profile) && !e.ctrlKey && !e.metaKey && !e.altKey && !typingIn(e.target)) {
    e.preventDefault(); // Shift can produce the semantic slash on another keyboard layout.
    if (!e.repeat) focusSearch();
  }
}
document.addEventListener("keydown", editorKeys);


// ------------------------------------------------------------------ sheets

/** A dialog (components.css dialog.sheet): a bottom sheet on phones, a box in the middle on wider screens,
 * and with side a panel on the right from 1,280 px (for editing a row beside its list). Closing it (the ×,
 * Escape, a tap outside it) calls onClose. Called as openSheet(title, opts) or openSheet({title, ...opts}),
 * where opts may also give body (nodes for the sheet's body) and actions (sheetActions' list). Returns
 * {dialog, heading, body, foot, closed, close(result)}. decklab/UI-KIT.md has the rules. */
function openSheet(title, opts = {}) {
  if (title && typeof title === "object") { opts = title; title = opts.title || ""; }
  const { onClose, wide, side } = opts;
  const id = `sheet-${++sheetIds}`;
  const heading = el("h2", { id, text: title });
  const body = el("div", { class: "sheet-body" });
  const foot = el("div", { class: "sheet-foot" });
  const close = el("button", { type: "button", class: "btn btn-quiet sheet-close", "aria-label": "Close", text: "×" });
  const dialog = el("dialog", { class: "sheet" + (wide ? " sheet-wide" : "") + (side ? " sheet-side" : ""), "aria-labelledby": id },
    el("div", { class: "sheet-inner" }, el("div", { class: "sheet-head" }, heading, close), body, foot));
  const sheet = { dialog, heading, body, foot, closed: false, result: null, entry: null,
    close(result) { if (result !== undefined) sheet.result = result; if (dialog.open) dialog.close(); else finish(); } };
  function finish() {
    if (sheet.closed) return;
    sheet.closed = true;
    dialog.remove();
    releaseSheetEntry(sheet.entry);     // core.js: Back steps off its entry, unless Back closed it
    if (onClose) onClose(sheet.result);
  }
  close.addEventListener("click", () => sheet.close());
  dialog.addEventListener("click", (e) => {
    if (e.target === dialog) sheet.close();                                  // outside the sheet
    else sheetLinkClick(e, sheet.entry, () => sheet.close());               // a link: its page takes the entry
  });
  dialog.addEventListener("close", finish);
  document.body.append(dialog);
  if (opts.body) add(body, [opts.body]);
  if (opts.actions) sheetActions(sheet, opts.actions);
  if (typeof dialog.showModal === "function") dialog.showModal();
  else dialog.setAttribute("open", "");
  // A history entry, so a phone's Back closes the sheet (not the page). history: false for a sheet opened while
  // the browser is moving through history (the editor's "Leave without saving?").
  if (opts.history !== false) sheet.entry = pushSheetEntry(() => sheet.close());
  trackEditorSearchDockSheet(sheet);
  return sheet;
}

/** Buttons for a sheet's foot: [{text, kind: "primary" | "danger" | "discard" | "", onclick}] ("discard" is
 * "Discard my changes": neither accent nor red; "danger" a destructive answer, "danger btn-quiet" Remove…). */
function sheetActions(sheet, actions) {
  clear(sheet.foot).append(...actions.filter(Boolean).map((a) => el("button", {
    type: "button", class: `btn${a.kind ? ` btn-${a.kind}` : ""}`, disabled: a.disabled || null, onclick: a.onclick,
    "data-action": a.value || null }, a.text)));
}

/** Ask a question in a sheet; resolves with the chosen value, or null if it was closed. opts: openSheet's
 * history. */
function ask(title, paragraphs, choices, opts = {}) {
  return new Promise((resolve) => {
    const sheet = openSheet(title, { onClose: (result) => resolve(result == null ? null : result), history: opts.history });
    sheet.body.append(...paragraphs.map((p) => el("p", { text: p })));
    sheetActions(sheet, choices.map((c) => ({ ...c, onclick: () => sheet.close(c.value) })));
    const first = sheet.foot.querySelector(".btn-primary");
    if (first) first.focus();
  });
}

// What a busy button held before its spinner (its words and any other nodes, such as Save's unsaved dot).
const busyNodes = new WeakMap();

function busy(button, text) {
  button.disabled = true;
  // Busy again (a second step of the same save): what it held before the first stays the thing to put back.
  if (!busyNodes.has(button)) {
    busyNodes.set(button, [...(button.childNodes || [])]);
    button.dataset.text = button.textContent;
  }
  button.dataset.busy = "1";
  button.setAttribute("aria-busy", "true");
  clear(button).append(el("span", { class: "spinner spinner-small", "aria-hidden": "true" }), text);
}

function unbusy(button) {
  button.disabled = false;
  delete button.dataset.busy;
  button.removeAttribute("aria-busy");
  const nodes = busyNodes.get(button);
  busyNodes.delete(button);
  if (nodes && nodes.length) clear(button).append(...nodes);
  else button.textContent = button.dataset.text || button.textContent;
}
