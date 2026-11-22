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

function openDeckLinkImport(fallbackText = "") {
  const ed = editor;
  if (!editorKeyboardCurrent(ed) || ed.saving || ed.asking || ed.leaving) return null;
  const sheet = openSheet("Import a deck link", {wide: true});
  const owner = editorImportOwner(ed, sheet);
  const input = el("input", {id: "deck-import-url", type: "url", maxlength: "500", autocomplete: "off",
    spellcheck: "false", autocapitalize: "off"});
  const result = el("p", {class: "form-error", "aria-live": "polite"});
  const review = el("button", {type: "submit", class: "btn btn-primary", text: "Review the deck"});
  const paste = el("button", {type: "button", class: "btn", text: "Paste a list", onclick: event => {
    if (!editorImportHere(owner, event.currentTarget)) return;
    sheet.close();
    openPaste(fallbackText ? {text: fallbackText} : null);
  }});
  const form = el("form", {id: "deck-import-link", novalidate: true},
    el("label", {class: "field", for: input.id}, el("span", {text: "Public Moxfield or Archidekt deck URL"}), input),
    result);
  let sequence = 0;
  input.addEventListener("input", () => {
    sequence += 1;
    result.textContent = "";
  });
  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (!editorImportHere(owner, review)) return;
    const link = input.value.trim(), request = ++sequence;
    if (!link) {
      result.textContent = "Paste a link to the deck first.";
      return;
    }
    result.textContent = "";
    busy(review, "Reading deck…");
    try {
      const answer = await apiWrite("/api/decklist/parse", {link, context: editorImportContext(ed)});
      if (!editorImportHere(owner) || sequence !== request) return;
      sheet.close();
      openPaste({text: answer.source_text, title: "Review imported list", answer});
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
      if (editorImportHere(owner) && sequence === request) result.textContent = error.message;
    } finally {
      if (review.isConnected) unbusy(review);
    }
  });
  review.setAttribute("form", "deck-import-link");
  sheet.body.append(form);
  sheet.foot.append(el("button", {type: "button", class: "btn", text: "Cancel", onclick: () => sheet.close()}), paste, review);
  input.focus();
  return sheet;
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
    el("span", { text: seeded?.answer ? "Imported list text" : "Text from Arena, MTGO, Moxfield or ManaBox" }), area));
  if (!seeded?.answer && !seeded?.check) sheet.body.append(el("button", {type: "button", class: "btn btn-quiet", text: "Import a deck link…",
    onclick: event => {
      if (!editorImportHere(owner, event.currentTarget)) return;
      sheet.close();
      openDeckLinkImport(area.value);
    }}));
  sheet.body.append(choiceHost, result);
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
      presentParsed(answer);
    } catch (e) {
      if (!(e instanceof ApiError)) throw e;
      if (editorImportHere(owner) && request === parseSequence)
        clear(result).append(el("div", { class: "box box-crit" }, el("p", { text: `The list couldn't be read: ${e.message}` })));
    } finally {
      unbusy(checkButton);
    }
  }

  function presentParsed(answer) {
    parsed = answer;
    choices = editorImportChoices(ed, parsed.sections, parsed, !!seeded?.answer);
    drawEditorImportChoices(choiceHost, choices, () => { if (editorImportHere(owner)) drawParsed(); });
    drawParsed();
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
  if (seeded?.answer) presentParsed(seeded.answer);
  else if (seeded?.check) check();
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

/** The starting choices share the usual editor, import review and collection readers. */
function startFromPart() {
  const ed = editor;
  const inventory = seesInventory(ed.space);
  const act = (name, action) => el("button", {type: "button", class: "btn", text: name,
    onclick: event => { if (editorKeyboardCurrent(ed) && event.currentTarget.isConnected) action(); } });
  return el("div", { class: "empty edit-start" },
    el("div", { class: "actions" },
      act("Start empty", openEditorSearchDock),
      act("Import a list", () => openPaste({text: "", title: "Import a list"})),
      inventory && createTargets().some(target => target.space === ed.space)
        ? act("Build from my cards", () => openEditorCollectionStarter(ed)) : null,
      ed.tonight && !ed.notice && !isDirty() ? el("button", { type: "button", class: "btn", text: "Review collection draft",
        onclick: event => { if (editor === ed && event.currentTarget.isConnected) openTonightDraft(ed.tonight); } }) : null),
    el("details", {class: "more"}, el("summary", {text: "Other ways to start"}),
      el("div", {class: "actions"},
        act("Copy another deck’s planned list", openDeckStart),
        inventory ? act("Use a published precon list", openPreconStart) : null,
        inventory ? act("Try a precon", () => openTrialSearch(ed.space)) : null,
        inventory && ed.space === ownSpace() ? el("a", {class: "btn", text: "I own this precon",
          href: ownedPreconHref(ed.space)}) : null),
      inventory ? el("p", {class: "sub", text: "Using a list fills this draft. Trying a precon saves a deck idea for simulations. Recording an owned precon adds its cards after review."}) : null));
}

function openEditorCollectionStarter(ed) {
  if (!editorKeyboardCurrent(ed) || ed.mode !== "new" || ed.from || ed.saving || ed.asking || ed.leaving
      || !seesInventory(ed.space) || Object.values(ed.lists).some(lines => lines.length)
      || !createTargets().some(target => target.space === ed.space)) return null;
  const sheet = colOpenSheet("Build from my cards"), owner = editorImportOwner(ed, sheet), initial = ed.snap;
  const choose = (text, action) => el("button", {type: "button", class: "btn", text, onclick: event => {
    if (!editorImportHere(owner, event.currentTarget) || ed.snap !== initial) return;
    sheet.close();
    action();
  }});
  sheet.body.append(el("p", {class: "sub", text: `Find a starting list using copies recorded in ${colWhose(ed.space)}.`}),
    el("div", {class: "actions"},
      choose("Find cards to add", () => openEditorSearchDock("collection")),
      ed.fields.kind === "commander" ? choose("Find commanders", () => openEditorCommanderCandidates(ed)) : null,
      choose("Find precons I can build", () => openCoverageSheet({space: ed.space, profile: ed.profile,
        token: owner.token, root: owner.page}))));
  return sheet;
}

/** Choose in the current editor so a title, player or other draft details stay in place. */
function openEditorCommanderCandidates(ed) {
  if (!editorKeyboardCurrent(ed) || ed.mode !== "new" || ed.fields.kind !== "commander" || ed.from
      || Object.values(ed.lists).some(lines => lines.length) || !seesInventory(ed.space)
      || !createTargets().some(target => target.space === ed.space)) return null;
  const sheet = colOpenSheet("Commanders we could build", { wide: true });
  const owner = editorImportOwner(ed, sheet), initial = ed.snap;
  const ownsReply = () => editorImportHere(owner, null, true, false) && ed.snap === initial;
  return commanderCandidatesSheet(ed.space, sheet, ownsReply, (candidate, tonight) => {
    if (!editorImportHere(owner) || ed.snap !== initial) return;
    const faces = candidateFaces(candidate);
    const params = new URLSearchParams({ space: ed.space, commander: faces[0].name });
    if (faces[1]) params.set("partner", faces[1].name);
    sheet.close();
    if (tonight) openTonightDraft(params, true);
    else applyCollectionDraft(faces, []);
  });
}

/** A sheet with a search box and a list of choices drawn by find(text) → Promise<[{label, sub, value}]>.
 * words: what it says while it looks ("Looking for precons…"), what failed ("The precons", for loadFailed),
 * none (nothing at all) and noMatch(text) (nothing for that search). */
function choiceSheet(title, placeholder, words, find, onPick) {
  const ed = editor;
  if (!editorKeyboardCurrent(ed) || ed.saving || ed.asking || ed.leaving) return null;
  const sheet = openSheet({ title, wide: true });
  const owner = editorImportOwner(ed, sheet), initial = ed.snap;
  const here = (sequence, control = null) => sequence === seq && ed.snap === initial && editorImportHere(owner, control);
  const input = el("input", { type: "search", class: "search-input", placeholder, "aria-label": placeholder, autocomplete: "off" });
  const list = el("ul", { class: "choice-list", "aria-live": "polite" });
  let seq = 0, timer = 0;
  const run = async () => {
    const mine = ++seq;
    if (!here(mine)) return;
    clear(list).append(el("li", {}, loadingBox(words.looking, { small: true })));
    const q = input.value.trim();
    let items;
    try {
      items = await find(q);
    } catch (e) {
      if (!(e instanceof ApiError)) throw e;
      if (here(mine)) clear(list).append(el("li", {}, loadFailed(words.what, e, () => run())));
      return;
    }
    if (!here(mine)) return;
    clear(list).append(...(items.length ? items.map((item) => el("li", {}, el("button", { type: "button", class: "choice-item",
      onclick: async event => {
        const button = event.currentTarget;
        if (!here(mine, button)) return;
        busy(button, "Loading…");
        if (await onPick(item.value, () => here(mine) && button.isConnected)) sheet.close();
        else if (button.isConnected) unbusy(button);
      } },
    el("b", { text: item.label }), item.sub ? el("small", { text: item.sub }) : null)))
      : [el("li", {}, q ? emptyBox(words.noMatch(q), el("button", { type: "button", class: "btn btn-quiet", text: "Clear the search",
        onclick: () => { input.value = ""; clearTimeout(timer); run(); input.focus(); } }))
        : emptyBox(words.none))]));
  };
  input.addEventListener("input", () => {
    seq++;
    clear(list);
    clearTimeout(timer);
    timer = setTimeout(run, 250);
  });
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
  return choiceSheet("Use a published precon list", "Search precons, e.g. Goblins", { looking: "Looking for precons…", what: "The precons",
    none: "No precons found.", noMatch: (q) => `No precons have “${q}” in their name.` }, async (q) => {
    const a = await api(`/api/precons${q ? `?q=${encodeURIComponent(q)}` : ""}`);
    return (a.decks || []).map((d) => ({ label: d.name, sub: [d.set_name || d.code.toUpperCase(), d.type, d.released].filter(Boolean).join(" · "),
      value: d }));
  }, async (deck, here) => {
    let p;
    try {
      p = await api(`/api/precons/preview?file=${encodeURIComponent(deck.file)}&space=${encodeURIComponent(ed.space || HOME_SPACE)}`);
    } catch (e) {
      if (!(e instanceof ApiError)) throw e;
      if (here()) toast(`That precon couldn't be read: ${e.message}`);
      return false;
    }
    if (!here()) return false;
    if (!norm("title", ed.fields.title)) ed.fields.title = p.title;
    if (!ed.from && p.kind && p.kind !== ed.fields.kind) setField("kind", p.kind, false);
    const n = mergeLines(p.lists || {});
    drawDetails();
    toast(`Started from ${deck.name}: ${plural(n, "card")}.`);
    return true;
  });
}

/** "Another deck": any deck in the library; its planned list goes into the new deck (it stays as it is). */
function openDeckStart() {
  return choiceSheet("Copy another deck’s planned list", "Search decks", { looking: "Looking for decks…", what: "The decks",
    none: "No decks yet.", noMatch: (q) => `No decks have “${q}” in their title.` }, async (q) => {
    const library = state.library || await api("/api/decks");
    const words = q.toLowerCase().split(/\s+/).filter(Boolean);
    return (library.decks || []).filter((d) => words.every((w) => d.title.toLowerCase().includes(w)))
      .slice(0, 40).map((d) => ({ label: d.title, sub: d.format || FORMAT_WORDS[d.kind] || "", value: d }));
  }, async (deck, here) => {
    let view;
    try {
      view = await api(`/api/deck/edit?id=${encodeURIComponent(deck.id)}`);
    } catch (e) {
      if (!(e instanceof ApiError)) throw e;
      if (here()) toast(`That deck couldn't be read: ${e.message}`);
      return false;
    }
    if (!here()) return false;
    const n = mergeLines(view.lists.target || {});
    toast(`Started from ${deck.title}: ${plural(n, "card")}.`);
    return true;
  });
}

/** Review a candidate against physical copies before adding its list to the new editor. */
function openTonightDraft(params, fromEditor = false) {
  const ed = editor, space = params.get("space") || HOME_SPACE;
  if (!editorKeyboardCurrent(ed) || ed.mode !== "new" || ed.space !== space ||
      !createTargets().some(target => target.space === space)) return null;
  if ((!fromEditor && (ed.notice || ed.dirty)) || ed.fields.kind !== "commander"
      || Object.values(ed.lists).some(lines => lines.length)) {
    toast("Your unsaved new deck is still here. Save or discard it before building from the collection.");
    return null;
  }
  const name = params.get("commander"), partner = params.get("partner");
  const sheet = colOpenSheet("Build from cards free tonight", { wide: true });
  const owner = editorImportOwner(ed, sheet);
  const locks = el("textarea", { rows: 3, placeholder: "One card name per line" });
  locks.value = ed.tonightLocks || "";
  const status = el("p", { role: "status", "aria-live": "polite" });
  const result = el("div");
  const refresh = el("button", { type: "button", class: "btn", text: "Preview draft" });
  const accept = el("button", { type: "button", class: "btn btn-primary", text: "Use this draft", hidden: true });
  sheet.body.append(el("h3", { text: [name, partner].filter(Boolean).join(" and ") }),
    el("p", { class: "sub", text: "Picks fill missing roles and look for cards that support the commander’s abilities. The preview explains each pick. You can change the list and check combos and its bracket in the editor." }),
    el("label", { class: "field" }, el("span", { text: "Theme cards to keep" }), locks), status, result);
  sheet.foot.append(el("button", { type: "button", class: "btn", text: "Cancel", onclick: () => sheet.close() }), refresh, accept);
  let request = 0, preview = null;
  function here(control) { return editorImportHere(owner, control) && ed.snap === initial; }
  const initial = ed.snap;
  function invalidate() {
    request++;
    preview = null;
    accept.hidden = true;
    status.textContent = "";
    clear(result);
  }
  locks.addEventListener("input", () => {
    if (!here(locks)) return;
    ed.tonightLocks = locks.value;
    invalidate();
  });
  async function loadDraft() {
    if (!here(refresh)) return;
    invalidate();
    const seq = request, written = locks.value || "";
    const locked = written.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
    status.textContent = "Finding cards free tonight…";
    try {
      const answer = await apiWrite("/api/commanders/draft", { space, name, ...(partner ? { partner } : {}), locked });
      if (!here() || seq !== request || written !== (locks.value || "")) return;
      preview = answer;
      drawTonightDraft(result, answer);
      status.textContent = `${answer.picked} of ${answer.target} cards outside the command zone. ${plural(answer.open_slots, "open slot")} (${answer.open_lands} lands, ${answer.open_spells} spells).`;
      accept.hidden = false;
    } catch (error) {
      if (here() && seq === request) status.textContent = error.message;
    }
  }
  refresh.addEventListener("click", loadDraft);
  accept.addEventListener("click", () => {
    if (!here(accept) || !preview || accept.hidden) return;
    sheet.close();
    applyCollectionDraft(preview.commanders, preview.picks);
  });
  loadDraft();
  return sheet;
}

function applyCollectionDraft(commanders, picks) {
  const ed = editor;
  if (!norm("title", ed.fields.title)) {
    const fronts = commanders.map(row => row.name.split(" // ")[0]);
    ed.fields.title = (fronts.length === 1 ? fronts[0] : fronts.map(n => n.split(",")[0]).join(" and ")).slice(0, 100);
  }
  ed.addSection = "Deck";
  mergeLines({
    Commander: commanders.map(row => ({ qty: 1, name: row.name, card: row.card })),
    Deck: picks.map(row => ({ qty: row.quantity, name: row.name, card: row.card })),
  });
  drawDetails();
}

function drawTonightDraft(host, draft) {
  const picks = draft.picks.map(row => el("li", {}, el("strong", { text: `${row.quantity} × ${row.name}` }),
    ` — ${row.reason}`, row.assumed_basic && row.locked ? " Uses the assumed ordinary basic-land supply." : ""));
  clear(host);
  add(host, [warningsBox(draft.warnings || [], "Commander draft notes")]);
  host.append(el("h3", { text: "Role coverage" }),
    el("p", { class: "sub" }, "Includes commanders. A card can cover several roles.",
      draft.source ? el("span", {}, " Targets from ", el("a", { href: draft.source.url, target: "_blank", rel: "noopener", text: draft.source.title }), ".") : ""),
    el("ul", {}, draft.roles.map(row => el("li", { text: `${row.label}: ${row.count} of ${row.target}` }))),
    el("h3", { text: "Mana sources" }), el("p", { text: draft.mana_sources.map(row => `${row.colour}: ${row.count}`).join(" · ") || "Colourless identity" }),
    el("h3", { text: "Draft picks" }));
  if (draft.affinity_source) host.append(el("p", { class: "sub" }, "Inclusion figures from ",
    el("a", { href: draft.affinity_source, target: "_blank", rel: "noopener", text: "EDHREC" }), "."));
  host.append(el("ul", {}, picks));
  if (draft.incoming.length) host.append(el("details", {}, el("summary", { text: "On the way (outside this draft)" }),
    el("ul", {}, draft.incoming.map(row => el("li", { text: `${row.quantity} × ${row.name}` })))));
}
