/* Deck Lab's editor: stand-ins for a card missing from the Play-now list (E2-S07).

Loaded after editor-cards.js and before editor-save.js. On the Play-now list (#/edit?…&v=owned), a short
Deck or Sideboard line's ⋯ menu has "Stand-ins…" (in the full editor and the phone's Quick edit), which
opens a sheet (a bottom sheet on a phone, a dialog on a tablet, the right-hand panel from 1,280 px) of
the owned cards that could take its place: POST /api/deck/swaps with the list as it is now (lib/api/swaps.py;
the same type, a shared colour, mana value within 1, free for this deck; the rules are in
lib/decks/swaps.py). "Use n" swaps them in: the missing line loses n copies, the stand-in goes into the
same section, and the Substitutes write-up gets the swap's note once (withSwapNote: a row of its table, or a
bullet), which the person then edits on the Notes tab. Deck Lab never writes that note again, so it stays as
edited. One change: Ctrl+Z or the toast's Undo takes back the list and the note together.

The deck page's Missing filter links here as #/edit?id=<deck>&v=owned&swap=<card name> (deck-swaps.js),
and its Swaps section's "Edit notes" as …&v=owned&tab=notes: openSwapsFromRoute starts the Play-now list
when there's none yet and opens the sheet for that card. Uses editor.js's lines, history and sheets,
editor-lines.js's startOwned, editor-cards.js's Add panel, editor-save.js's currentAvailability, and
cards-ui.js's cardRow.
*/
"use strict";

const SWAP_SECTIONS = ["Deck", "Sideboard"];      // where a missing card may be swapped (lib/decks/swaps.py)
const SWAP_TABLE = ["| Buy (Planned list) | Play now | What the swap costs |", "|---|---|---|"];

/** True when a line of the list being edited may get stand-ins: the Play-now list, a Deck or Sideboard
 * line the last check says is short, and a space whose collection the visitor may see. */
function swapsAvailableFor(line) {
  const ed = editor;
  if (!ed || ed.mode !== "edit" || ed.version !== "owned" || noOwnedList() || !seesInventory(ed.space)) return false;
  const found = findLine(line.uid);
  if (!found || !SWAP_SECTIONS.includes(found.section)) return false;
  const a = currentAvailability();
  const row = a && (a.rows || []).find((r) => r.name === line.name);
  return Boolean(row && row.missing > 0);
}

/** The whole-word rule for a card's name in the write-up (lib/decks/swaps.py _pattern): not part of a
 * longer word, and a double-faced card by its front face too. (noteNaming also takes out longer card
 * names that name it, as names_card does: "Anger of the Gods" doesn't name Anger.) */
function swapNamePattern(name) {
  const names = [...new Set([name, name.split(" // ")[0]].map((n) => n.toLowerCase()))]
    .sort((a, b) => b.length - a.length).map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  return new RegExp(`(?:^|[^\\w'])(?:${names.join("|")})(?=$|[^\\w'])`);
}

/** The first line of the Substitutes text that names the card (a table's |---| line never does), or null.
 * others are the other card names in play (both lists'): a longer one naming this card inside it is taken
 * out of each line first. */
function noteNaming(text, name, others = []) {
  const pattern = swapNamePattern(name);
  const longer = [...new Set(others.map((n) => n.toLowerCase()))]
    .filter((n) => n.length > name.length && n !== name.toLowerCase() && pattern.test(n))
    .sort((a, b) => b.length - a.length);
  for (const line of String(text || "").split("\n")) {
    if (!line.trim() || /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$/.test(line)) continue;
    const words = longer.reduce((t, n) => t.split(n).join(" ~ "), line.toLowerCase());
    if (pattern.test(words)) return line;
  }
  return null;
}

/** The card names of the list being edited and the Planned list (noteNaming's others). */
function swapListNames(ed) {
  const names = (lists) => Object.values(lists || {}).flat().map((l) => l.name);
  return [...names(ed.lists), ...names(ed.view && ed.view.lists && ed.view.lists.target)];
}

/** The Substitutes text with a swap's note added (swap: {outQty, outName, inQty, inName, note}), in the
 * section's own style: a row at the end of its table (one of 3 or more columns whose headings say where the
 * stand-in goes, swapColumns), else a bullet, else a new table when the section is empty. */
function withSwapNote(text, swap) {
  const lines = String(text || "").replace(/\s+$/, "").split("\n");
  if (lines.length === 1 && !lines[0]) return [...SWAP_TABLE, swapRow(swap, swapColumns(SWAP_TABLE[0]))].join("\n");
  const rule = (l) => /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*){2,}\|?\s*$/.test(l);
  let head = -1;
  lines.forEach((l, i) => { if (i + 1 < lines.length && l.trim().startsWith("|") && rule(lines[i + 1])) head = i; });
  const columns = head >= 0 ? swapColumns(lines[head]) : null;
  if (columns) {
    let end = head + 2;
    while (end < lines.length && lines[end].trim().startsWith("|")) end += 1;
    lines.splice(end, 0, swapRow(swap, columns));
    return lines.join("\n");
  }
  const bullet = `- **${swap.outQty} ${swap.outName} → ${swap.inQty} ${swap.inName}:** ${swap.note}`;
  const last = lines[lines.length - 1];
  return [...lines, ...(/^\s*[-*+]\s/.test(last) ? [] : [""]), bullet].join("\n");
}

/** Where a table's row puts each part, from its heading row: {count, out, in, note} (column indexes), or
 * null when no heading says where the stand-in goes ("Stand-in", "Play now", "Owned"): then a bullet.
 * The missing card goes under "Buy", "Planned", "Target", "Missing" or "Out", else the first column; the
 * note in the last free column (where swaps.py's note_of reads it). */
function swapColumns(header) {
  const heads = header.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((h) => h.trim().toLowerCase());
  if (heads.length < 3) return null;
  const find = (pattern, not = []) => heads.findIndex((h, i) => !not.includes(i) && pattern.test(h));
  let out = find(/\b(buy|planned|target|missing|out)\b/);
  if (out < 0) out = 0;
  let into = find(/stand-?in/, [out]);
  if (into < 0) into = find(/\bplay/, [out]);
  if (into < 0) into = find(/\bowned\b/, [out]);
  const note = heads.length - 1;
  if (into < 0 || note === out || note === into) return null;
  return { count: heads.length, out, in: into, note };
}

function swapRow(swap, columns) {
  const cells = Array(columns.count).fill(" ");
  cells[columns.out] = `${swap.outQty} ${swap.outName}`;
  cells[columns.in] = `${swap.inQty} ${swap.inName}`;
  cells[columns.note] = swap.note;
  return `| ${cells.join(" | ")} |`;
}

/** "Creature, red, mana value 3–5" (a land: "Land, red and green"). */
function swapLooksFor(entry) {
  const type = entry.type ? entry.type[0].toUpperCase() + entry.type.slice(1) : "Card";
  const colours = entry.colours.length ? entry.colours.map((c) => COLOUR_WORDS[c]).join(" and ") : "colourless";
  const mv = entry.type === "land" ? null : `mana value ${Math.max(0, entry.mv - 1)}–${entry.mv + 1}`;
  return [type, colours, mv].filter(Boolean).join(", ");
}

/** A candidate's facts: "3 mana · 2 free", "1 here, 2 on the way", or "Basic land". */
function swapCandidateMeta(c) {
  if (c.basic) return "Basic land";
  const copies = c.here === c.free ? `${c.free} free` : !c.here ? `${c.free} on the way` : `${c.here} here, ${c.free - c.here} on the way`;
  return c.card && c.card.type_line && /\bLand\b/.test(c.card.type_line) ? copies : `${num(c.card ? c.card.cmc : 0)} mana · ${copies}`;
}

/** The stand-ins sheet for a line of the Play-now list. */
async function openSwapSheet(uid) {
  const ed = editor;
  const found = ed && findLine(uid);
  if (!found) return;
  const name = found.line.name;
  const hash = location.hash, profile = state.profile && state.profile.id;
  const here = () => editor === ed && !ed.leaving && location.hash === hash && (state.profile && state.profile.id) === profile;
  const sheet = openSheet({ title: `Stand-ins for ${name}`, side: true });
  sheet.dialog.classList.add("swap-sheet");
  sheet.body.append(loadingBox("Looking through your cards…"));
  let answer;
  try {
    answer = await apiWrite("/api/deck/swaps", { id: ed.id, list: sendList(ed.lists), card: name });
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    if (here() && !sheet.closed) clear(sheet.body).append(el("p", { class: "form-error", role: "alert", text: e.message }));
    return;
  }
  if (!here() || sheet.closed) return;          // a late answer: the editor, the page or the person changed
  drawSwapSheet(sheet, uid, answer.cards[0], answer);
}

function drawSwapSheet(sheet, uid, entry, answer) {
  const price = entry.aud_each != null
    ? `Buying it: about ${aud(entry.aud_each)} each${answer.price_date ? ` (prices of ${answer.price_date})` : ""}.` : null;
  const rows = entry.candidates.map((c) => {
    const n = Math.max(1, c.max_qty);
    const chips = !c.basic && !c.here ? [status("info", "On the way")] : [];
    return el("li", { class: "swap-row" },
      cardRow(c.card, { name: c.name, meta: swapCandidateMeta(c), chips, viewerGroup: "editor-swaps",
        caption: `${c.name} for ${entry.name}` }),
      el("p", { class: "sub swap-note", text: c.note.text }),
      el("button", { type: "button", class: "btn swap-use", "aria-label": `Use ${n} ${c.name} for ${entry.name}`,
        text: `Use ${n}`, onclick: () => { sheet.close(); applySwap(uid, entry, c, n); } }));
  });
  add(clear(sheet.body), [
    el("p", { class: "sub swap-head", text: `${plural(entry.missing, "copy", "copies")} missing · ${swapLooksFor(entry)}` }),
    price ? el("p", { class: "sub", text: price }) : null,
    rows.length ? el("ul", { class: "swap-list" }, rows) : el("div", { class: "empty swap-none" },
      el("p", { text: "No free card fits (the same type, a shared colour, mana value within 1)." }),
      el("button", { type: "button", class: "btn", text: "Search My collection",
        onclick: () => { sheet.close(); searchCollectionFor(entry, answer); } })),
    entry.more ? el("p", { class: "sub", text: `${plural(entry.more, "more card fits", "more cards fit")}; these are the closest.` }) : null]);
}

/** The Add panel's My collection, in the missing card's type and colours (else the deck's). */
function searchCollectionFor(entry, answer) {
  const ed = editor;
  if (!ed) return;
  ed.addSection = entry.section;
  focusSearch();
  const ac = ed.ac;
  if (!ac) return;
  ac.mode = "collection";
  ac.colors = new Set(entry.colours.length ? entry.colours : answer.colours || []);
  ac.type = entry.type && FIND_TYPES.some(([value]) => value === entry.type) ? entry.type : "";
  ac.mv = "";
  ac.filtersOpen = true;
  drawAddTo();
  refilter(ac);
}

/** Swap n copies of candidate c in for the missing line uid, and note it in Substitutes once. */
function applySwap(uid, entry, c, n) {
  const ed = editor;
  const found = ed && findLine(uid);
  if (!found) return;
  const { line, section, index } = found;
  const qty = Math.min(n, line.qty);
  if (line.qty > qty) line.qty -= qty;
  else ed.lists[section].splice(index, 1);
  const lines = ed.lists[section] || (ed.lists[section] = []);
  const d = c.default;
  let into = lines.find((l) => l.name === c.name && (d ? l.set === d.set && l.number === d.number && l.finish === d.finish : !l.set))
    || lines.find((l) => l.name === c.name);
  if (into) {
    into.qty = Math.min(MAX_COPIES, into.qty + qty);
  } else {
    into = newLine({ qty, name: c.name, set: d && d.set, number: d && d.number, finish: d ? d.finish : "nonfoil", card: c.card });
    placeLine(lines, into);
  }
  ed.flash = into.uid;
  const prose = (ed.prose && ed.prose.substitutes) || "";
  const names = swapListNames(ed);
  const noted = noteNaming(prose, line.name, names);
  if (!noted) {
    ed.prose = { ...(ed.prose || {}), substitutes: withSwapNote(prose,
      { outQty: qty, outName: line.name, inQty: qty, inName: c.name, note: c.note.text }) };
  }
  syncSections();
  changed();
  const after = ed.snap;
  const words = noted
    ? `${c.name} is in for ${qty} ${line.name}. ${line.name} already has a note in Substitutes; check it still fits` +
      (noteNaming(noted, c.name, names) ? "." : ` (it doesn't name ${c.name}).`)
    : `${c.name} is in for ${qty} ${line.name}. Note added to Substitutes.`;
  showToast(words, { undo: () => {
    // Only while nothing has changed since: then it's the last step Ctrl+Z would take back.
    if (editor !== ed) return;
    if (ed.snap === after && undoLast()) toast("Swap undone.");
    else toast("Other changes came after the swap: Ctrl+Z steps back through them, or change it by hand.");
  } });
}

/** #/edit?…&v=owned&swap=<name> and &tab=notes: what the deck page's links open (deck-swaps.js). */
function openSwapsFromRoute(params, id) {
  const ed = editor;
  const swap = params.get("swap"), tab = params.get("tab");
  if (!ed || ed.mode !== "edit" || ed.id !== id || (!swap && tab !== "notes")) return;
  const previousHash = location.hash, canonicalHash = editHref(ed.id, ed.version);
  history.replaceState(history.state, "", canonicalHash);
  canonicalEditorPaneHash(ed, previousHash, canonicalHash);
  if (tab === "notes") {
    ed.tab = "notes";
    drawMain();
  }
  if (!swap || ed.version !== "owned") return;
  if (noOwnedList()) startOwned();
  const line = SWAP_SECTIONS.flatMap((s) => editor.lists[s] || []).find((l) => l.name === swap);
  if (line) openSwapSheet(line.uid);
  else toast(`${swap} isn't in the ${listName("owned", true)} any more.`);
}
