/* Deck Lab's editor: Paste/replace and Start from workflows (E11-S37), and a new deck started from a
 * commander (#/new?kind=commander&commander=<name>: Commanders we could build's New deck from it, E9-S28).
 * Loaded directly after editor-cards.js and editor-edhrec.js. These functions use the editor state,
 * list/draft helpers and sheets from editor.js, changed() from editor-screen.js,
 * Deck details from editor-details.js, and Add controls from editor-cards.js.
 * Shared state and viewport listeners stay in their existing owners.
 */
"use strict";

// ------------------------------------------------------------------ pasting

/** Lists with sections' lines merged in (the same printing in the same section goes on one line), as a copy. */
function mergedLists(lists, sections) {
  const out = copyList(lists);
  for (const [name, lines] of Object.entries(sections)) {
    const section = name === "Commander" && currentKind() !== "commander" ? "Deck" : name;
    const into = out[section] || (out[section] = []);
    for (const line of lines) {
      const same = into.find((l) => lineKey(l) === lineKey(line));
      if (same) same.qty = Math.min(MAX_COPIES, same.qty + line.qty);
      else placeLine(into, newLine(line));
    }
  }
  return out;
}

/** The pasted sections as the whole list (Replace). */
function replacedLists(sections) {
  return mergedLists({}, sections);
}

function openPaste(seed = null) {
  const ed = editor;
  if (!editorKeyboardCurrent(ed) || ed.saving || ed.asking || ed.leaving) return null;
  const seeded = seed && typeof seed.text === "string" ? seed : null;
  const sheet = openSheet(seeded?.title || "Paste a list", { wide: true });
  const owner = editorImportOwner(ed, sheet);
  const area = el("textarea", { id: "paste-text", class: "paste-area", rows: 9, spellcheck: "false",
    autocapitalize: "off", autocomplete: "off",
    placeholder: "Deck\n4 Llanowar Elves (FDN) 227\n2 Lightning Bolt\n9 Forest\n\nSideboard\n2 Negate (FDN) 47" });
  const result = el("div", { class: "paste-result", "aria-live": "polite" }), choiceHost = el("div", {class: "paste-choices"});
  let parsed = null, choices = null, parseSequence = 0;
  let mode = "add";
  const has = Object.values(ed.lists).some((lines) => lines.length);
  sheet.body.append(el("label", { class: "field", for: "paste-text" },
    el("span", { text: "Text from Arena, MTGO, Moxfield or ManaBox" }), area), choiceHost, result);
  const checkButton = el("button", { type: "button", class: "btn btn-primary", text: "Check the list" });
  const applyButton = el("button", { type: "button", class: "btn btn-primary", hidden: true });
  sheet.foot.append(el("button", { type: "button", class: "btn", text: "Cancel", onclick: () => sheet.close() }),
    checkButton, applyButton);
  area.addEventListener("input", () => {
    parseSequence += 1;
    if (!parsed) return;
    parsed = null; choices = null; clear(choiceHost);
    applyButton.hidden = true;
    checkButton.hidden = false;
    clear(result);
  });

  async function check() {
    if (!editorImportHere(owner, checkButton)) return;
    if (!area.value.trim()) {
      clear(result).append(el("p", { class: "form-error", text: "Paste or type a list first." }));
      return;
    }
    busy(checkButton, "Checking…");
    const written = area.value, request = ++parseSequence;
    try {
      const answer = await apiWrite("/api/decklist/parse", { text: written, context: editorImportContext(ed) });
      if (!editorImportHere(owner) || request !== parseSequence || written !== area.value) return;
      parsed = answer; choices = editorImportChoices(ed, parsed.sections, parsed);
      drawEditorImportChoices(choiceHost, choices, () => {if (editorImportHere(owner)) drawParsed();});
      drawParsed();
    } catch (e) {
      if (!(e instanceof ApiError)) throw e;
      if (editorImportHere(owner) && request === parseSequence)
        clear(result).append(el("div", { class: "box box-crit" }, el("p", { text: `The list couldn't be read: ${e.message}` })));
    } finally {
      unbusy(checkButton);
    }
  }

  function fixLine(u, name, control) {
    if (!editorImportHere(owner, control)) return;
    const rows = area.value.replace(/\r\n?/g, "\n").split("\n");
    const row = rows[u.line - 1] || "";
    rows[u.line - 1] = row.includes(u.name) ? row.replace(u.name, name) : `${u.qty} ${name}`;
    area.value = rows.join("\n");
    parsed = null; choices = null; clear(choiceHost);
    check();
  }

  function drawParsed() {
    if (!editorImportHere(owner) || !parsed) return;
    const p = parsed;
    updateEditorImportMarks(choices, mode);
    const selected = editorImportSections(choices);
    const selectedCards = Object.values(selected).flat().reduce((n, line) => n + line.qty, 0);
    const after = mode === "replace" ? replacedLists(selected) : mergedLists(ed.lists, selected);
    const diff = listChanges(ed.lists, after);
    const modeSwitch = has && p.count.lines ? el("div", { class: "segmented", role: "group", "aria-label": "What to do with the list" },
      [["add", "Add to the list"], ["replace", "Replace the list"]].map(([key, label]) => el("button", { type: "button",
        "aria-pressed": String(mode === key), onclick: event => { if (editorImportHere(owner, event.currentTarget)) {mode = key; drawParsed();} } }, label))) : null;
    const shown = diff.slice(0, 40);
    const kinds = diff.reduce((m, c) => { m[changeKind(c)] = (m[changeKind(c)] || 0) + 1; return m; }, {});
    const summary = [kinds.added ? `${kinds.added} added` : "", kinds.removed ? `${kinds.removed} taken out` : "",
      kinds.changed ? `${kinds.changed} changed` : ""].filter(Boolean).join(" · ");
    add(clear(result), [
      p.count.lines ? null : el("p", {}, status("warn", "Nothing to add"), " No line of the list names a card Deck Lab knows."),
      p.unknown.length ? el("div", { class: "box box-crit" },
        el("h3", { text: `Not card names Deck Lab knows (${p.unknown.length}): left out` }),
        el("ul", {}, p.unknown.map((u) => el("li", {},
          el("span", { text: `Line ${u.line}: ${u.text}. ` }),
          u.suggestions.length
            ? ["Did you mean ", u.suggestions.map((s, i) => [i ? " or " : "",
              el("button", { type: "button", class: "chip-btn", text: s, onclick: event => fixLine(u, s, event.currentTarget) })]), "?"]
            : "No close match: check the spelling.")))) : null,
      p.errors.length ? el("div", { class: "box box-warn" },
        el("h3", { text: `Lines that aren't cards (${p.errors.length}): skipped` }),
        el("ul", {}, p.errors.map((e) => el("li", { text: `Line ${e.line}: ${e.text}. ${capitalise(e.error)}.` })))) : null,
      p.warnings.length ? warningsBox(p.warnings, "Notes") : null,
      modeSwitch,
      summary ? el("p", { class: "paste-summary" }, el("b", { text: summary })) : null,
      diff.length ? el("ul", { class: "review-list paste-diff" }, shown.map((c) => el("li", { class: `review-${changeKind(c)}` },
        el("span", { class: "review-mark", "aria-hidden": "true", text: { added: "+", removed: "−", changed: "~" }[changeKind(c)] }),
        changeWords(c)))) : p.count.lines ? el("p", { class: "sub", text: "The list already has these cards." }) : null,
      diff.length > shown.length ? el("p", { class: "sub", text: `and ${diff.length - shown.length} more changes` }) : null]);
    applyButton.hidden = !selectedCards || (!diff.length && mode === "add");
    checkButton.hidden = !!p.count.lines;
    applyButton.textContent = mode === "replace" ? "Replace the list" : `Add ${plural(selectedCards, "card")}`;
    applyButton.className = "btn btn-primary" + (mode === "replace" ? " btn-danger" : "");
  }

  checkButton.addEventListener("click", check);
  applyButton.addEventListener("click", event => {
    if (!parsed || !choices || !editorImportHere(owner, event.currentTarget)) return;
    const selected = editorImportSections(choices);
    const left = parsed.unknown.length;
    const n = Object.values(selected).flat().reduce((total, line) => total + line.qty, 0);
    if (!n) return;
    if (mode === "replace") replaceLines(selected);
    else mergeLines(selected);
    sheet.close();
    // The toast's Undo takes back this paste only: after any later change it would undo that instead.
    const before = ed.history[ed.history.length - 1];
    const after = ed.snap;
    showToast((mode === "replace" ? `Replaced the list with ${plural(n, "card")}` : `Added ${plural(n, "card")}`) +
      (left ? `; ${plural(left, "line")} with unknown names left out.` : "."), { undo: () => {
      if (editor === ed && ed.snap === after && ed.history[ed.history.length - 1] === before) undoLast();
      else toast("Other changes came after the paste, so it can't be undone on its own: Ctrl+Z takes changes back one at a time.");
    } });
  });
  if (seeded) area.value = seeded.text;
  area.focus();
  if (seeded?.check) check();
  return sheet;
}

/** Add lines to the list: the same printing in the same section goes on one line. */
function mergeLines(sections) {
  const ed = editor;
  ed.lists = mergedLists(ed.lists, sections);
  return afterBulkChange(sections);
}

/** The list becomes these sections. */
function replaceLines(sections) {
  const ed = editor;
  ed.lists = replacedLists(sections);
  ed.removed = [];
  return afterBulkChange(sections);
}

function afterBulkChange(sections) {
  const ed = editor;
  ed.lastAdded = null;
  syncSections();
  if (ed.dom.addTo) drawAddTo();
  changed();
  return Object.values(sections).reduce((n, lines) => n + lines.reduce((m, l) => m + l.qty, 0), 0);
}


// --------------------------------------------------------------- starting from

/** A new Commander deck started from a commander (E9-S28's New deck from it): the card goes in the Commander
 * section as one change (one Undo step, kept in the draft), titled with its name when the title is empty.
 * A draft of a new deck already holding cards is kept as it is, and says why the commander wasn't added.
 * The address loses commander= either way, so a reload brings back the draft and never adds it twice. */
async function startFromCommander(name, partner = null) {
  const ed = editor;
  const names = partner && partner !== name ? [name, partner] : [name];
  const params = new URLSearchParams({ kind: "commander" });
  if (ed.space && ed.space !== HOME_SPACE) params.set("space", ed.space);
  if (location.hash.startsWith("#/new?")) history.replaceState(history.state, "", `#/new?${params}`);
  const lines = Object.values(ed.lists).reduce((n, list) => n + list.length, 0);
  if (lines) {
    const already = names.every((n) => (ed.lists.Commander || []).some((l) => l.name === n));
    if (!already) toast(`Your unsaved new deck is still here, so ${names.join(" and ")} ${names.length > 1 ? "weren't" : "wasn't"} added. Save or discard it, then start from the commander again.`);
    return false;
  }
  const found = [];
  for (const n of names) {
    let answer;
    try {
      answer = await api(`/api/cards/search?q=${encodeURIComponent(n)}&limit=20&detail=1`);
    } catch (e) {
      if (!(e instanceof ApiError)) throw e;
      if (editor === ed) toast(`${n} couldn't be looked up: ${e.message}`);
      return false;
    }
    if (editor !== ed || ed.mode !== "new") return false;
    const card = ((answer && answer.cards) || []).find((c) => c.name === n);
    if (!card) { toast(`${n} isn't a card Deck Lab knows. Add the commander with the search.`); return false; }
    found.push(card);
  }
  if (ed.fields.kind !== "commander") setField("kind", "commander", false);
  if (!norm("title", ed.fields.title)) {
    const both = names.map((n) => n.split(" // ")[0].split(",")[0]).join(" and ");
    ed.fields.title = names.length > 1 && both.length <= 100 ? both : name.split(" // ")[0];
  }
  if (found.length === 1) {
    ed.addSection = "Commander";
    addCard(found[0], "Commander");
  } else {
    // A pair (E9-S28's third slice): both commanders go in as one change, one Undo step.
    const lines = ed.lists.Commander || (ed.lists.Commander = []);
    for (const c of found) {
      const d = c.default;
      placeLine(lines, newLine({ qty: 1, name: c.name, set: d && d.set, number: d && d.number,
        finish: d ? d.finish : "nonfoil", card: cardData(c) }));
    }
    ed.addSection = "Deck";
    syncSections();
    changed();
    toast(`${names.join(" and ")} are the commanders. New cards go to ${sectionTitle("Deck")} now.`);
  }
  drawDetails();
  return true;
}

/** A new deck with no cards yet: start from a paste, a precon or another deck. */
function startFromPart() {
  const ed = editor;
  const precon = seesInventory(ed.space || HOME_SPACE);
  // One action that fills it (a pasted list); a precon and another deck are quieter ways to the same start.
  return el("div", { class: "empty edit-start" },
    el("p", { text: precon ? "Add cards with the search, or start from a pasted list, a precon or another deck."
      : "Add cards with the search, or start from a pasted list or another deck." }),
    el("div", { class: "actions" },
      el("button", { type: "button", class: "btn", text: "Paste a list…", onclick: openPaste }),
      precon ? el("button", { type: "button", class: "btn btn-quiet", text: "A precon…", onclick: openPreconStart }) : null,
      el("button", { type: "button", class: "btn btn-quiet", text: "Another deck…", onclick: openDeckStart })));
}

/** A sheet with a search box and a list of choices drawn by find(text) → Promise<[{label, sub, value}]>.
 * words: what it says while it looks ("Looking for precons…"), what failed ("The precons", for loadFailed),
 * none (nothing at all) and noMatch(text) (nothing for that search). */
function choiceSheet(title, placeholder, words, find, onPick) {
  const sheet = openSheet({ title, wide: true });
  const input = el("input", { type: "search", class: "search-input", placeholder, "aria-label": placeholder, autocomplete: "off" });
  const list = el("ul", { class: "choice-list", "aria-live": "polite" });
  let seq = 0, timer = 0;
  const run = async () => {
    const mine = ++seq;
    clear(list).append(el("li", {}, loadingBox(words.looking, { small: true })));
    const q = input.value.trim();
    let items;
    try {
      items = await find(q);
    } catch (e) {
      if (!(e instanceof ApiError)) throw e;
      if (mine === seq && !sheet.closed) clear(list).append(el("li", {}, loadFailed(words.what, e, () => run())));
      return;
    }
    if (mine !== seq || sheet.closed) return;
    clear(list).append(...(items.length ? items.map((item) => el("li", {}, el("button", { type: "button", class: "choice-item",
      onclick: async (e) => { busy(e.currentTarget, "Loading…"); if (await onPick(item.value)) sheet.close(); else unbusy(e.currentTarget); } },
    el("b", { text: item.label }), item.sub ? el("small", { text: item.sub }) : null)))
      : [el("li", {}, q ? emptyBox(words.noMatch(q), el("button", { type: "button", class: "btn btn-quiet", text: "Clear the search",
        onclick: () => { input.value = ""; clearTimeout(timer); run(); input.focus(); } }))
        : emptyBox(words.none))]));
  };
  input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(run, 250); });
  sheet.body.append(input, list);
  sheetActions(sheet, [{ text: "Cancel", onclick: () => sheet.close() }]);
  input.focus();
  run();
  return sheet;
}

/** "A precon": MTGJSON's paper decks (GET /api/precons), and the picked one's lists (its preview, which
 * changes nothing) go into the new deck. */
function openPreconStart() {
  const ed = editor;
  choiceSheet("Start from a precon", "Search precons, e.g. Goblins", { looking: "Looking for precons…", what: "The precons",
    none: "No precons found.", noMatch: (q) => `No precons have “${q}” in their name.` }, async (q) => {
    const a = await api(`/api/precons${q ? `?q=${encodeURIComponent(q)}` : ""}`);
    return (a.decks || []).map((d) => ({ label: d.name, sub: [d.set_name || d.code.toUpperCase(), d.type, d.released].filter(Boolean).join(" · "),
      value: d }));
  }, async (deck) => {
    let p;
    try {
      p = await api(`/api/precons/preview?file=${encodeURIComponent(deck.file)}&space=${encodeURIComponent(ed.space || HOME_SPACE)}`);
    } catch (e) {
      if (!(e instanceof ApiError)) throw e;
      toast(`That precon couldn't be read: ${e.message}`);
      return false;
    }
    if (editor !== ed) return true;
    if (!norm("title", ed.fields.title)) ed.fields.title = p.title;
    if (!ed.from && p.kind && p.kind !== ed.fields.kind) setField("kind", p.kind);
    const n = mergeLines(p.lists || {});
    drawDetails();
    toast(`Started from ${deck.name}: ${plural(n, "card")}.`);
    return true;
  });
}

/** "Another deck": any deck in the library; its planned list goes into the new deck (it stays as it is). */
function openDeckStart() {
  const ed = editor;
  choiceSheet("Start from another deck", "Search decks", { looking: "Looking for decks…", what: "The decks",
    none: "No decks yet.", noMatch: (q) => `No decks have “${q}” in their title.` }, async (q) => {
    if (!state.library) cacheLibrary(await api("/api/decks"));
    if (!state.library) return [];
    const words = q.toLowerCase().split(/\s+/).filter(Boolean);
    return state.library.decks.filter((d) => words.every((w) => d.title.toLowerCase().includes(w)))
      .slice(0, 40).map((d) => ({ label: d.title, sub: d.format || FORMAT_WORDS[d.kind] || "", value: d }));
  }, async (deck) => {
    let view;
    try {
      view = await api(`/api/deck/edit?id=${encodeURIComponent(deck.id)}`);
    } catch (e) {
      if (!(e instanceof ApiError)) throw e;
      toast(`That deck couldn't be read: ${e.message}`);
      return false;
    }
    if (editor !== ed) return true;
    const n = mergeLines(view.lists.target || {});
    toast(`Started from ${deck.title}: ${plural(n, "card")}.`);
    return true;
  });
}
