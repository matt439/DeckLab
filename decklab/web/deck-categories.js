/* A deck builder's own card categories (E2-S24): "Ramp", "Draw", "Win condition", one per decklist line.

The deck text keeps each as a " #Ramp" at the end of its line (decklab/lib/decks/decklist.py), and the page's
lines carry it as `category` (absent when a line has none). Here: the deck page's Cards tab grouped by category
instead of card type (deckGroups' "category", the rest under Uncategorised), the Stats tab's count per category,
the Chance to draw panel's one-tap ticks for a category, and the editor's ⋯ > Category… sheet, which only someone
who may edit the deck reaches (the editor is theirs). Nothing here talks to the server: the editor's Save writes
the categories with the list (editor.js sendLine).

Loaded after deck.js, stats.js and the editor's scripts, whose helpers (mergedLines, byCostThenName, barList,
cardNames, openSheet, findLine, changed) it uses at run time; nothing runs at load.
*/
"use strict";

const CATEGORY_MAX = 30;            // decklist.py's CATEGORY_MAX
// decklist.py's CATEGORY_RE: letters and digits at both ends, a few joiners between. The server decides.
const CATEGORY_RE = new RegExp(`^[\\p{L}\\p{N}](?:[\\p{L}\\p{N}_ '&/+.-]{0,${CATEGORY_MAX - 2}}[\\p{L}\\p{N}])?$`, "u");
const UNCATEGORISED = "Uncategorised";
const CARDS_GROUP_KEY = "deck.cardsGroup";      // localStorage: "type" or "category", the Cards tab's last choice

/** A category as typed, as a line holds it: spaces squeezed, a leading "#" dropped; "" for none. */
function cleanCategory(text) {
  return String(text || "").trim().replace(/\s+/g, " ").replace(/^#+/, "").trim();
}

function validCategory(text) { return text === "" || CATEGORY_RE.test(text); }

/** The categories of some lines, each once whatever its case, in alphabetical order. A category written
 * two ways ("Ramp", "ramp") is shown as the spelling most lines use, capitals first on a tie. */
function categoryNames(lines) {
  const seen = new Map();
  for (const line of lines) {
    const key = (line.category || "").toLowerCase();
    if (!key) continue;
    const spellings = seen.get(key) || new Map();
    spellings.set(line.category, (spellings.get(line.category) || 0) + 1);
    seen.set(key, spellings);
  }
  return [...seen.values()].map((spellings) => [...spellings].sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1))[0][0])
    .sort((a, b) => a.localeCompare(b));
}

function sameCategory(line, category) {
  return (line.category || "").toLowerCase() === (category || "").toLowerCase();
}

/** Every line of a deck view's lists: {section: [line]}. */
function allSectionLines(sections) { return Object.values(sections || {}).flat(); }

function deckHasCategories(data) { return allSectionLines(data && data.sections).some((l) => l.category); }

/** "category" when the viewer last chose it and this list has categories, else "type". */
function cardsGrouping(data) {
  return local.get(CARDS_GROUP_KEY) === "category" && deckHasCategories(data) ? "category" : "type";
}

/** The Cards tab's "Group by Type | Category" switch, only for a list with categories. */
function cardsGroupingToggle(data, redraw) {
  if (!deckHasCategories(data)) return null;
  const now = cardsGrouping(data);
  return el("div", { class: "segmented deck-group-by", role: "group", "aria-label": "Group the cards by" },
    [["type", "Type"], ["category", "Category"]].map(([by, words]) => el("button", { type: "button", text: words,
      "aria-pressed": String(now === by), onclick: () => { local.set(CARDS_GROUP_KEY, by); redraw(); } })));
}

/** A section's merged lines as deckGroups' groups, one per category, Uncategorised last. */
function categoryGroups(section, lines) {
  const names = categoryNames(lines);
  const groups = names.map((title) => ({ section, title, lines: lines.filter((l) => sameCategory(l, title)) }));
  const rest = lines.filter((l) => !l.category);
  if (rest.length) groups.push({ section, title: UNCATEGORISED, lines: rest });
  for (const g of groups) g.lines.sort(byCostThenName);
  return groups;
}

/** The copies in each category of the cards that count towards the deck (the Commander and the Deck):
 * [{category, count, cards: [{name, qty, card}]}], Uncategorised last; [] when no line has a category. */
function categoryCounts(sections) {
  const lines = ["Commander", "Deck"].flatMap((s) => mergedLines((sections || {})[s] || [], true));
  const names = categoryNames(lines);
  if (!names.length) return [];
  const item = (category, members) => ({ category, count: copies(members),
    cards: members.sort(byCostThenName).map((l) => ({ name: l.name, qty: l.qty, card: l.card })) });
  const out = names.map((name) => item(name, lines.filter((l) => sameCategory(l, name))));
  const rest = lines.filter((l) => !l.category);
  if (rest.length) out.push(item(UNCATEGORISED, rest));
  return out;
}

/** The Stats tab's "Your categories": each category's copies in the deck, its cards a tap away. null for
 * a list with no categories. */
function categoriesPanel(data) {
  const counts = categoryCounts(data && data.sections);
  if (!counts.length) return null;
  return el("section", { class: "panel", "aria-labelledby": "h-categories" },
    el("h3", { id: "h-categories", text: "Your categories" }),
    el("p", { class: "sub", text: "Copies in each category you've given the deck's cards (the sideboard isn't counted). " +
      "Tap a row to list its cards." }),
    barList(counts, (c) => c.category));
}

/** The Chance to draw panel's buttons that tick a category's cards (setAll(test)), one per category. Its
 * lines are merged by name (mergedLines): a card with a copy in the category is ticked, every copy counted. */
function oddsCategoryButtons(lines, setAll) {
  const given = (line) => (line.categories || [line.category]).filter(Boolean).map((category) => ({ category }));
  return categoryNames(lines.flatMap(given)).map((name) => el("button", { type: "button", class: "btn btn-quiet",
    text: name, "aria-label": `Tick every ${name} card`,
    onclick: () => setAll((line) => given(line).some((c) => sameCategory(c, name))) }));
}

/** The editor's ⋯ > Category…: give a line a category (the deck's others offered), change it or clear it.
 * The change is the editor's like any other: Undo takes it back and Save writes it. */
function openCategorySheet(uid) {
  const ed = editor;
  const found = findLine(uid);
  if (!ed || ed.readOnly || !found) return null;
  const line = found.line;
  const listId = `category-names-${uid}`;
  const others = categoryNames(allSectionLines(ed.lists));
  const input = el("input", { type: "text", maxlength: String(CATEGORY_MAX + 1), autocomplete: "off",
    autocapitalize: "sentences", enterkeyhint: "done", list: listId, placeholder: "e.g. Ramp, Draw, Removal",
    onkeydown: (e) => { if (e.key === "Enter") { e.preventDefault(); save(); } } });
  input.value = line.category || "";
  const error = el("p", { class: "form-error", role: "alert" });
  const sheet = openSheet(`Category for ${line.name}`);
  sheet.body.append(
    el("p", { class: "sub", text: "Your own label for what the card does in this deck. The Cards tab can group the " +
      "list by it and the Stats tab counts it." }),
    el("label", { class: "field" }, el("span", { text: "Category" }), input),
    el("datalist", { id: listId }, others.map((name) => el("option", { value: name }))),
    error);
  function apply(value) {
    line.category = value || null;
    sheet.close();
    changed();
    toast(value ? `${line.name}: ${value}.` : `${line.name} has no category now.`);
  }
  function save() {
    const value = cleanCategory(input.value);
    if (!validCategory(value)) {
      error.textContent = `A category is 1 to ${CATEGORY_MAX} letters, digits and spaces (and - ' & / + .), ` +
        "starting and ending with a letter or digit.";
      input.focus();
      return;
    }
    // The deck's own spelling of a category it already has, so "ramp" joins "Ramp".
    apply(others.find((name) => name.toLowerCase() === value.toLowerCase()) || value);
  }
  sheetActions(sheet, [
    { text: "Cancel", onclick: () => sheet.close() },
    line.category ? { text: "Clear", kind: "danger btn-quiet", onclick: () => apply("") } : null,
    { text: "Set category", kind: "primary", onclick: save }]);
  input.focus();
  return sheet;
}
