/* Tickable same-space deck/paste imports. Availability is by card name, never a printing promise. */
"use strict";

function editorImportContext(ed) { return ed.mode === "edit" ? {id: ed.id} : {space: ed.space || HOME_SPACE}; }

function editorImportOwner(ed, sheet) {
  return {ed, sheet, page: ed.dom.page, token: routeToken, profile: ed.profile, frame: keyboardEditorFrame(ed),
    hash: location.hash, signature: listSignature(ed.lists), readOnly: !!ed.readOnly};
}

function editorImportHere(owner, control = null, unchanged = true) {
  const {ed, sheet} = owner;
  return editorKeyboardCurrent(ed) && ed.dom.page === owner.page && owner.token === routeToken && owner.profile === state.profile?.id
    && owner.frame === keyboardEditorFrame(ed) && owner.hash === location.hash && !ed.saving && !ed.asking && !ed.leaving
    && !!ed.readOnly === owner.readOnly
    && (!unchanged || owner.signature === listSignature(ed.lists)) && !sheet.closed && sheet.dialog.isConnected
    && [...document.querySelectorAll("dialog[open]")].at(-1) === sheet.dialog
    && (!control || control.isConnected && sheet.dialog.contains(control) && !control.disabled);
}

function editorImportIdentity(ed) {
  if ((ed.mode === "new" ? ed.fields.kind : ed.kind) !== "commander") return null;
  const commanders = ed.lists.Commander || [];
  if (!commanders.length || commanders.length > 2 || commanders.some(line => !editorImportColours(line.card?.color_identity))) return false;
  return new Set(commanders.flatMap(line => line.card.color_identity));
}

function editorImportColours(value) {
  return Array.isArray(value) && value.length <= 5 && new Set(value).size === value.length
    && value.every(colour => typeof colour === "string" && colour.length === 1 && "WUBRG".includes(colour));
}

function editorImportCopyLimit(card) {
  const type = (card?.type_line || "").split(" // ")[0];
  if (/\bBasic\b/.test(type) && /\bLand\b/.test(type)) return Infinity;
  if (card && Object.hasOwn(card, "commander_copies")) {
    if (card.commander_copies === null) return Infinity;
    if (Number.isSafeInteger(card.commander_copies) && card.commander_copies > 0) return card.commander_copies;
  }
  // Older kept drafts already carry Oracle text. Match the server's existing Commander rule.
  const match = /a deck can have (any number of|up to (\w+)|only one) cards? named|your deck can have (only one) copy of this card/i.exec(card?.oracle_text || "");
  if (!match || match[1] === "only one" || match[3]) return 1;
  if (match[1].toLowerCase() === "any number of") return Infinity;
  const words = {one:1,two:2,three:3,four:4,five:5,six:6,seven:7,eight:8,nine:9,ten:10,eleven:11,twelve:12};
  return /^\d+$/.test(match[2]) ? Number(match[2]) : words[match[2].toLowerCase()] || 1;
}

function editorImportCounts(sections) {
  const counts = new Map();
  for (const line of Object.values(sections || {}).flat()) {
    const name = line.card?.name || line.name;
    counts.set(name, (counts.get(name) || 0) + line.qty);
  }
  return counts;
}

function editorImportChoices(ed, sections, answer = {}) {
  const identity = editorImportIdentity(ed), base = editorImportCounts(ed.lists), anticipated = new Map(base);
  const rows = [];
  for (const [section, lines] of Object.entries(sections || {})) for (const line of lines) {
    const name = line.card?.name || line.name, limit = editorImportCopyLimit(line.card);
    const duplicate = identity !== null && ((anticipated.get(name) || 0) + line.qty > limit);
    const unknown = identity !== null && (identity === false || !editorImportColours(line.card?.color_identity));
    const outside = identity && !unknown && line.card.color_identity.some(colour => !identity.has(colour));
    const reason = duplicate ? "Already in this draft" : unknown ? "Colour identity isn't confirmed" : outside ? "Outside the commander's colour identity" : "";
    rows.push({section, line, selected: !reason, reason});
    if (!reason) anticipated.set(name, (anticipated.get(name) || 0) + line.qty);
  }
  return {rows, answer, base};
}

function editorImportSections(choices) {
  const sections = {};
  for (const item of choices.rows) if (item.selected) (sections[item.section] ||= []).push(item.line);
  return sections;
}

function editorImportMarks(line, answer, allocation = null) {
  if (!answer.marks || !answer.availability) return null;
  const row = (answer.availability.rows || []).find(item => item.name === line.name);
  if (!row) return el("small", {class: "sub", text: line.card?.type_line?.includes("Basic") ? "Basic land copies aren't tracked" : "Availability not confirmed"});
  const held = (row.in_use_elsewhere || []).reduce((n, item) => n + item[1], 0) + (row.lent_out || 0);
  const free = allocation ? allocation.free : Math.max(0, row.owned - row.on_the_way - held), words = [];
  if (free > 0) words.push(`${free} free`);
  if (held > 0) words.push(`${held} in use${row.in_use_elsewhere?.length ? ` (${row.in_use_elsewhere.map(item => item[0]).join(", ")})` : ""}`);
  const coming = allocation ? allocation.incoming : row.on_the_way, buying = allocation ? allocation.buy : row.missing;
  if (coming > 0) words.push(`${coming} on the way`);
  if (buying > 0) words.push(`${buying} to buy`);
  return el("small", {class: "import-availability", text: `${allocation?.selected === false ? "Unticked; if added: " : ""}${words.join(" · ") || "No free copy confirmed"}`});
}

function updateEditorImportMarks(choices, mode = "add") {
  const remaining = new Map(), allocations = new Map();
  for (const row of choices.answer.availability?.rows || []) {
    const held = (row.in_use_elsewhere || []).reduce((n,item)=>n+item[1],0) + (row.lent_out || 0);
    const physical = Math.max(0, row.owned - row.on_the_way - held), base = mode === "add" ? choices.base.get(row.name) || 0 : 0;
    const usableIncoming = Math.min(row.on_the_way, Math.max(0,row.available-physical));
    remaining.set(row.name, {free: Math.max(0, physical-base), incoming: Math.max(0, usableIncoming-Math.max(0,base-physical))});
  }
  for (const selected of [true,false]) for (const item of choices.rows.filter(row=>row.selected===selected)) {
    const stock = remaining.get(item.line.name);
    if (!stock) continue;
    const free = Math.min(item.line.qty,stock.free), incoming = Math.min(item.line.qty-free,stock.incoming);
    allocations.set(item,{free,incoming,buy:item.line.qty-free-incoming,selected});
    if (selected) {stock.free-=free;stock.incoming-=incoming;}
  }
  for (const item of choices.rows) if (item.markHost) add(clear(item.markHost), [editorImportMarks(item.line,choices.answer,allocations.get(item))]);
}

function drawEditorImportChoices(host, choices, changedSelection) {
  clear(host);
  host.append(el("p", {class: "sub", text: choices.answer.marks
    ? "Availability is by card name. Add uses copies left after this draft and earlier selected rows; Replace uses only the selected list. Check the printings. Nothing is reserved or saved."
    : choices.answer.availability_error || "This collection isn't yours to see, so no availability is shown."}));
  if (choices.answer.availability?.warnings?.length) add(host, [warningsBox(choices.answer.availability.warnings, "Availability notes")]);
  for (const item of choices.rows) {
    const checkbox = el("input", {type: "checkbox"}); checkbox.checked = item.selected;
    checkbox.addEventListener("change", () => {
      if (checkbox.isConnected && host.contains(checkbox) && !checkbox.disabled) {item.selected = checkbox.checked; changedSelection();}
    });
    item.markHost = el("span");
    host.append(el("label", {class: "choice import-choice"}, checkbox,
      el("span", {}, el("span", {text: `${item.line.qty} ${item.line.name} · ${item.section} · ${printingText(item.line)}${item.line.category ? ` · #${item.line.category}` : ""}`}),
        item.reason ? el("small", {text: item.reason}) : null, item.markHost)));
  }
  updateEditorImportMarks(choices);
}

/** Existing-deck imports choose only real decks in this editor's space. Every read is
 * tied to the original mounted page/person/frame; no library cache crosses profiles. */
function openDeckImport() {
  const ed = editor;
  if (!editorKeyboardCurrent(ed) || ed.mode !== "edit" || ed.readOnly || ed.saving || ed.asking || ed.leaving) return null;
  const sheet = openSheet({title: "Add cards from another deck", wide: true}), owner = editorImportOwner(ed, sheet);
  const query = el("input", {type: "search", class: "search-input", "aria-label": "Search decks", autocomplete: "off"});
  const list = el("div", {class: "choice-list"}), note = el("p", {class: "sub", "aria-live": "polite"});
  let decks = null, busyNow = false;
  function draw() {
    if (!editorImportHere(owner)) return;
    clear(list);
    const words = query.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const shown = (decks || []).filter(deck => words.every(word => deck.title.toLowerCase().includes(word))).slice(0, 40);
    for (const deck of shown) list.append(el("button", {type: "button", class: "btn choice-item", text: deck.title, onclick: async event => {
      const control = event.currentTarget;
      if (!editorImportHere(owner, control) || busyNow) return;
      busyNow = true; busy(control, "Loading…"); note.textContent = "Reading this deck's Planned list…";
      try {
        const source = await api(`/api/deck/edit?id=${encodeURIComponent(deck.id)}`);
        if (!editorImportHere(owner)) return;
        if (source.id !== deck.id || source.space !== (ed.space || HOME_SPACE) || !source.lists?.target) {
          note.textContent = "That deck's list is no longer available in this space. Refresh the choices before importing."; return;
        }
        const text = exportedDeck({sections: source.lists.target}, {categories: true});
        sheet.close(); openPaste({text, title: `Add cards from ${deck.title}`, check: true});
      } catch (_) {if (editorImportHere(owner)) note.textContent = "That deck couldn't be read. Your current draft is unchanged.";}
      finally {busyNow = false; if (control.isConnected) unbusy(control);}
    }}));
    note.textContent = shown.length ? "Choose a deck of your own space. Its cards are reviewed before anything is added."
      : decks ? "No other deck in this space matches." : "Loading your decks…";
  }
  query.addEventListener("input", draw); sheet.body.append(query, list, note);
  sheetActions(sheet, [{text: "Cancel", onclick: () => sheet.close()}]);
  api("/api/decks").then(answer => {
    if (!editorImportHere(owner)) return;
    decks = (answer.decks || []).filter(deck => deck.id !== ed.id && ["casual", "commander"].includes(deck.kind)
      && (deck.space || deckSpaceOf(deck.id)) === (ed.space || HOME_SPACE) && !deck.error && typeof deck.title === "string");
    draw();
  }).catch(() => {if (editorImportHere(owner)) note.textContent = "Your decks couldn't be loaded. The current draft is unchanged.";});
  draw(); query.focus(); return sheet;
}
