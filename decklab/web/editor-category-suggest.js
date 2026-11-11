/* Reviewed category proposals and private remembered choices. No automatic label or save. */
"use strict";

const CATEGORY_ROLE_PRIORITY = [["board wipe", "Board wipe"], ["counterspell", "Counterspell"],
  ["removal", "Removal"], ["draw", "Draw"], ["ramp", "Ramp"]];

function editorRoleCategory(card) {
  if (!card || !Array.isArray(card.roles)) return null;
  // Cached older drafts already have roles, even before card_lookup added the same proposal.
  return CATEGORY_ROLE_PRIORITY.find(([role]) => card.roles.includes(role))?.[1] || null;
}

function editorCategoryOwner(ed, sheet) {
  return {ed, sheet, page: ed.dom.page, token: routeToken, profile: ed.profile, frame: keyboardEditorFrame(ed), hash: location.hash};
}

function editorCategoryHere(owner, control = null) {
  const {ed, sheet} = owner;
  return editorKeyboardCurrent(ed) && ed.dom.page === owner.page && routeToken === owner.token && ed.profile === owner.profile
    && keyboardEditorFrame(ed) === owner.frame && location.hash === owner.hash && !ed.readOnly && !ed.saving && !ed.asking && !ed.leaving
    && !sheet.closed && sheet.dialog.isConnected && [...document.querySelectorAll("dialog[open]")].at(-1) === sheet.dialog
    && (!control || control.isConnected && sheet.dialog.contains(control) && !control.disabled);
}

function editorCategorySuggestButton() {
  const ed = editor;
  if (ed.readOnly || noOwnedList()) return null;
  const button = el("button", {type: "button", class: "btn btn-quiet edit-category-suggest", text: "Suggest categories…",
    onclick: event => {
      if (event.currentTarget.isConnected && ed === editor && editorKeyboardCurrent(ed) && ed.dom.page.contains(event.currentTarget)
          && ed.tab === "cards" && !document.querySelector("dialog[open]")) openCategorySuggestions(ed);
    }});
  ed.dom.categorySuggest = button;
  return button;
}

function updateEditorCategorySuggest() {
  const ed = editor, button = ed?.dom?.categorySuggest;
  if (button) {
    button.hidden = ed.tab !== "cards";
    button.disabled = !!(ed.readOnly || ed.saving || ed.asking || ed.leaving || noOwnedList());
  }
}

function openCategorySuggestions(ed = editor) {
  if (!editorKeyboardCurrent(ed) || ed.readOnly || ed.saving || ed.asking || ed.leaving || noOwnedList()) return null;
  const signature = listSignature(ed.lists), proposals = [];
  for (const [section, lines] of Object.entries(ed.lists)) for (const line of lines) {
    const category = !line.category && editorRoleCategory(line.card);
    if (category) proposals.push({section, line, category});
  }
  const sheet = openSheet({title: "Suggest categories", wide: true}), owner = editorCategoryOwner(ed, sheet);
  const error = el("p", {class: "form-error", role: "alert", hidden: true});
  sheet.body.append(el("p", {class: "sub", text:
    "Only untagged lines in this list are proposed. The fixed priority is Board wipe, Counterspell, Removal, Draw, then Ramp. Untick any line to leave it as it is."}));
  const selections = proposals.map(item => {
    const checkbox = el("input", {type: "checkbox"}); checkbox.checked = true;
    sheet.body.append(el("label", {class: "choice"}, checkbox, el("span", {text:
      `${item.line.qty} ${item.line.name} · ${item.section}${printingText(item.line) ? ` · ${printingText(item.line)}` : ""} → ${item.category}`})));
    return {...item, checkbox};
  });
  if (!selections.length) sheet.body.append(el("p", {text: "No untagged line has a known role to suggest. You can still set a category on any line."}));
  sheet.body.append(error);
  sheetActions(sheet, [{text: "Cancel", onclick: () => sheet.close()}, {text: "Apply selected categories", kind: "primary", disabled: !selections.length,
    onclick: event => {
      if (!editorCategoryHere(owner, event.currentTarget)) return;
      if (signature !== listSignature(ed.lists) || selections.some(item => findLine(item.line.uid)?.line !== item.line)) {
        error.hidden = false; error.textContent = "The list changed. Close this review and suggest categories for its current lines."; return;
      }
      const chosen = selections.filter(item => item.checkbox.checked);
      if (!chosen.length) {error.hidden = false; error.textContent = "Tick at least one category to apply."; return;}
      for (const item of chosen) if (!item.line.category) item.line.category = item.category;
      sheet.close(); changed(); toast(`${plural(chosen.length, "category", "categories")} applied. Save the deck to keep them.`);
    }}]);
  return sheet;
}

async function loadRememberedCategories(owner, line, choices, datalist, note) {
  const ed = owner.ed, space = ed.space || HOME_SPACE;
  const query = new URLSearchParams({name: line.name, space});
  if (ed.mode === "edit" && ed.id) query.set("exclude", ed.id);
  note.textContent = "Loading categories from your other decks…";
  try {
    const answer = await api(`/api/cards/categories?${query}`);
    if (!editorCategoryHere(owner) || findLine(line.uid)?.line !== line || !datalist.isConnected || !owner.sheet.dialog.contains(datalist)) return;
    const known = new Set(choices.map(value => value.toLowerCase()));
    for (const category of (Array.isArray(answer.categories) ? answer.categories : []).slice(0, 30)) {
      if (typeof category !== "string" || !category || !validCategory(category) || known.has(category.toLowerCase())) continue;
      known.add(category.toLowerCase()); choices.push(category); datalist.append(el("option", {value: category}));
    }
    note.textContent = "Choices include this card's labels in your own space's other decks. Nothing is applied automatically.";
  } catch (_) {
    if (editorCategoryHere(owner) && findLine(line.uid)?.line === line)
      note.textContent = "Other-deck categories couldn't load. This deck's choices and your typed label still work.";
  }
}
