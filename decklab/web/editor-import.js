/* Deck Lab's editor: Paste/replace and Start from workflows (E11-S37).
 * Loaded directly after editor-cards.js. These functions use the editor state,
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

function openPaste() {
  const ed = editor;
  const sheet = openSheet("Paste a list", { wide: true });
  const area = el("textarea", { id: "paste-text", class: "paste-area", rows: 9, spellcheck: "false",
    autocapitalize: "off", autocomplete: "off",
    placeholder: "Deck\n4 Llanowar Elves (FDN) 227\n2 Lightning Bolt\n9 Forest\n\nSideboard\n2 Negate (FDN) 47" });
  const result = el("div", { class: "paste-result", "aria-live": "polite" });
  let parsed = null;
  let mode = "add";
  const has = Object.values(ed.lists).some((lines) => lines.length);
  sheet.body.append(el("label", { class: "field", for: "paste-text" },
    el("span", { text: "Text from Arena, MTGO, Moxfield or ManaBox" }), area), result);
  const checkButton = el("button", { type: "button", class: "btn btn-primary", text: "Check the list" });
  const applyButton = el("button", { type: "button", class: "btn btn-primary", hidden: true });
  sheet.foot.append(el("button", { type: "button", class: "btn", text: "Cancel", onclick: () => sheet.close() }),
    checkButton, applyButton);
  area.addEventListener("input", () => {
    if (!parsed) return;
    parsed = null;
    applyButton.hidden = true;
    checkButton.hidden = false;
    clear(result);
  });

  async function check() {
    if (!area.value.trim()) {
      clear(result).append(el("p", { class: "form-error", text: "Paste or type a list first." }));
      return;
    }
    busy(checkButton, "Checking…");
    try {
      parsed = await apiWrite("/api/decklist/parse", { text: area.value });
      drawParsed();
    } catch (e) {
      if (!(e instanceof ApiError)) throw e;
      clear(result).append(el("div", { class: "box box-crit" }, el("p", { text: `The list couldn't be read: ${e.message}` })));
    } finally {
      unbusy(checkButton);
    }
  }

  function fixLine(u, name) {
    const rows = area.value.replace(/\r\n?/g, "\n").split("\n");
    const row = rows[u.line - 1] || "";
    rows[u.line - 1] = row.includes(u.name) ? row.replace(u.name, name) : `${u.qty} ${name}`;
    area.value = rows.join("\n");
    parsed = null;
    check();
  }

  function drawParsed() {
    const p = parsed;
    const after = mode === "replace" ? replacedLists(p.sections || {}) : mergedLists(ed.lists, p.sections || {});
    const diff = listChanges(ed.lists, after);
    const modeSwitch = has && p.count.lines ? el("div", { class: "segmented", role: "group", "aria-label": "What to do with the list" },
      [["add", "Add to the list"], ["replace", "Replace the list"]].map(([key, label]) => el("button", { type: "button",
        "aria-pressed": String(mode === key), onclick: () => { mode = key; drawParsed(); } }, label))) : null;
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
              el("button", { type: "button", class: "chip-btn", text: s, onclick: () => fixLine(u, s) })]), "?"]
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
    applyButton.hidden = !p.count.lines || (!diff.length && mode === "add");
    checkButton.hidden = !!p.count.lines;
    applyButton.textContent = mode === "replace" ? "Replace the list" : `Add ${plural(p.count.cards, "card")}`;
    applyButton.className = "btn btn-primary" + (mode === "replace" ? " btn-danger" : "");
  }

  checkButton.addEventListener("click", check);
  applyButton.addEventListener("click", () => {
    if (!parsed) return;
    const left = parsed.unknown.length;
    const n = parsed.count.cards;
    if (mode === "replace") replaceLines(parsed.sections || {});
    else mergeLines(parsed.sections || {});
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
  area.focus();
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
    if (!state.library) state.library = await api("/api/decks");
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
