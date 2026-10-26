/* Deck Lab's editor: the list on the Cards tab (Milestone 4; the layout of UI-REVIEW.md WP11).

Loaded after editor.js, editor-screen.js and editor-details.js and before editor-cards.js, editor-swaps.js,
editor-save.js and editor-deckpage.js (then matchups.js and the page's other scripts, core.js to app.js). It holds the
list's sections (dense rows or picture stacks, and the Quick edit's compact rows), a line's caption, ⋯
menu and steppers, typed quantities, removing a line ("Removed ... Undo"), Undo and moving a line to
another section, and starting the Play-now list. It uses editor.js's `editor`, lines and history,
editor-screen.js's changed(), the counts and the bar, editor-cards.js's Add panel and printing sheet, and
deck.js's card helpers.

Changing the list: a quantity counts as it's typed, and quantities, Remove and Undo change the rows,
the counts and the bar in place rather than drawing them again, so the tap that comes next lands on
what the finger went for. "−" on a line of 1 removes it; a removed line stays where it was as
"Removed ... Undo" (same height). Ctrl/Cmd+Z takes back any change (editor.js undoLast).
*/
"use strict";

// The list ------------------------------------------------------------------------

function sectionTitle(section) {
  return section === "Deck" && currentKind() === "commander" ? "The 99" : section;
}

/** An empty section's line, with its one action: "No commander yet. [Add a commander]". */
function emptyPart(section) {
  const ed = editor;
  if (section === "Commander") {
    return el("p", { class: "sub empty-section" }, "No commander yet.",
      noOwnedList() ? null : el("button", { type: "button", class: "btn", text: "Add a commander", onclick: () => {
        ed.addSection = "Commander";
        drawAddTo();
        queueDraft();
        focusSearch();
      } }));
  }
  if (section === "Deck") return el("p", { class: "sub empty-section", text: "No cards yet." });
  return null;
}

/** A count for a heading: nothing for zero (UI-KIT: zero counts aren't shown). */
function countWords(n) { return n ? String(n) : ""; }

/** Which way the list is drawn now: picture stacks or rows (the Quick edit always has rows). */
function visualLook() { return editor.look === "visual" && !editor.quick; }

function drawLines() {
  const ed = editor;
  const host = ed.dom.lines;
  if (!host) return;
  const focus = document.activeElement && host.contains(document.activeElement)
    ? document.activeElement.dataset.focus : null;
  clear(host);
  if (noOwnedList()) {
    host.append(el("div", { class: "empty edit-empty" },
      el("p", { text: `No ${listName("owned", true)} yet. It's the deck made only from cards you have or have on the way.` }),
      el("button", { type: "button", class: "btn btn-primary",
        text: `Start it from the ${listName("target", true)}`, onclick: startOwned })));
    return;
  }
  const kind = currentKind();
  const visual = visualLook();
  host.classList.toggle("is-visual", visual);
  const total = Object.values(ed.lists).reduce((n, lines) => n + lines.length, 0);
  if (!total && ed.mode === "new" && !ed.from) host.append(startFromPart());
  // A removed line stays where it was, as "Removed ... Undo", while the editor is open.
  const rows = (entries) => entries.sort((a, b) => byCostThenName(a.line, b.line))
    .map((x) => (x.gone ? removedRow(x.gone) : visual ? lineTile(x.line, x.section) : lineRow(x.line, x.section)));
  const list = (items) => el(visual ? "div" : "ul", { class: visual ? "edit-stacks" : "edit-list" }, items);
  for (const section of ed.sections) {
    const lines = ed.lists[section] || [];
    const entries = [...lines.map((line) => ({ line, section })),
      ...ed.removed.filter((g) => g.section === section).map((g) => ({ line: g.line, section, gone: g }))];
    if (!entries.length && section === "Commander" && kind !== "commander") continue;
    if (!entries.length && section === "Sideboard") continue;
    if (!entries.length && !total && ed.mode === "new" && !ed.from && section === "Deck") continue;
    const part = el("section", { class: "edit-section" + (section === "Sideboard" ? " edit-sideboard" : ""),
      "data-section": section, "aria-label": sectionTitle(section) },
      el("h3", { class: "section-title" }, sectionTitle(section),
        el("span", { class: "count", "data-count": section, text: countWords(copies(lines)) })));
    if (section === "Sideboard" && (kind === "casual" || kind === "commander")) {
      part.append(el("p", { class: "edit-sideboard-note", text: `Not counted in the ${kind === "commander" ? 100 : 60}.` }));
    }
    if (!entries.length) {
      add(part, [emptyPart(section)]);
    } else if (section === "Deck") {
      const groups = new Map(TYPE_GROUPS.map((g) => [g, []]));
      for (const x of entries) groups.get(typeGroup(x.line.card)).push(x);
      for (const [group, members] of groups) {
        if (!members.length) continue;
        const live = members.filter((x) => !x.gone).map((x) => x.line);
        part.append(el("h4", { class: "type-title" }, group,
          el("span", { class: "count", "data-count": `${section}:${group}`, text: countWords(copies(live)) })),
        list(rows(members)));
      }
    } else {
      part.append(list(rows(entries)));
    }
    host.append(part);
  }
  if (focus) {
    const again = host.querySelector(`[data-focus="${CSS.escape(focus)}"]`);
    if (again) again.focus({ preventScroll: true });
  }
  markRows();
  ed.flash = null;
}

/** The section and type counts in the list, after a change made in place (no redraw). */
function refreshCounts() {
  const ed = editor;
  if (!ed.dom.lines) return;
  for (const span of ed.dom.lines.querySelectorAll(".count[data-count]")) {
    const [section, group] = span.dataset.count.split(":");
    const lines = (ed.lists[section] || []).filter((l) => !group || typeGroup(l.card) === group);
    span.textContent = countWords(copies(lines));
  }
}

function startOwned() {
  const ed = editor;
  ed.starting = true;
  ed.lists = copyList(ed.view.lists.target);
  ed.removed = [];
  syncSections();
  drawEditor();
  changed({ list: false });
  toast(`The ${listName("owned", true)} starts as a copy of the ${listName("target", true)}.`);
}

/** The viewer's line for a line of the list: "2 copies · Deck · FDN 227". */
function lineCaption(line, section) {
  return `${plural(line.qty, "copy", "copies")} · ${sectionTitle(section)} · ${printingText(line)}`;
}

/** One line of the list, a dense row: − n +, the card (its art and name, which open the card viewer over
 * the whole list), at most one badge (filled by editor-save.js showRowAvailability when the card isn't
 * simply owned and free), its printing (the printing sheet), and ⋯ (change printing, move, remove). */
function lineRow(line, section) {
  const card = line.card;
  const open = card
    ? viewerItem(el("button", { type: "button", class: "edit-card", "aria-haspopup": "dialog",
      "aria-label": `See ${line.name}`, "data-focus": `card:${line.uid}`, onclick: (e) => openCard(card, e.currentTarget) },
    card.img_small ? el("img", { class: "edit-thumb", src: card.img_small, alt: "", loading: "lazy", decoding: "async",
      width: 40, height: 56 }) : el("span", { class: "edit-thumb thumb-missing", "aria-hidden": "true" }),
    el("span", { class: "nm" }, el("span", { class: "nm-text", text: line.name }), editor.quick ? null : manaCost(card.mana_cost, true))),
    card, "editor", lineCaption(line, section))
    : el("span", { class: "edit-card" }, el("span", { class: "edit-thumb thumb-missing", "aria-hidden": "true" }),
      el("span", { class: "nm" }, el("span", { class: "nm-text", text: line.name })));
  // The Quick edit shows the printing as words under the name; its ⋯ changes it (a 44 px row stays one row).
  // On a phone the name has the first line to itself; the cost goes before the printing on the second.
  const print = editor.quick ? el("span", { class: "edit-print-words" }, card ? manaCost(card.mana_cost, true) : null,
    el("span", { text: printingText(line) }))
    : el("button", { type: "button", class: "chip-btn edit-print", "data-focus": `print:${line.uid}`, "aria-haspopup": "dialog",
      "aria-label": `${line.name}: ${printingText(line)}. Change the printing`, onclick: () => openPrintings(line.uid) },
    printingText(line), el("span", { class: "caret", "aria-hidden": "true" }));
  const row = peekable(el("li", { class: "edit-row" + (editor.flash === line.uid ? " flash" : ""), "data-uid": line.uid },
    stepper(line, "row"),
    open,
    el("span", { class: "edit-badge-slot" }),
    print,
    rowMenuButton(line)), card);
  if (!card) row.append(el("p", { class: "edit-problem", text: "Not a card name in the card data; kept as written." }));
  return row;
}

/** A line in the Pictures look: the card's picture, stacked for its copies, with − n + under it. */
function lineTile(line, section) {
  // The badge sits on the picture's corner and the finish is in the meta line ("FDN 227 · foil", with the
  // sheen), so every tile's footer is − n + and ⋯ on one line.
  const tile = cardTile(line.card, { qty: line.qty, name: line.name, meta: printingText(line),
    viewerGroup: "editor", caption: lineCaption(line, section), state: el("span", { class: "edit-badge-slot" }),
    chips: [stepper(line, "tile"), rowMenuButton(line)] });
  tile.classList.add("edit-row", "edit-tile");
  if (line.finish === "foil" || line.finish === "etched") tile.classList.add(`is-${line.finish}`);
  if (editor.flash === line.uid) tile.classList.add("flash");
  tile.dataset.uid = String(line.uid);
  tile.setAttribute("data-uid", String(line.uid));
  tile.setAttribute("data-copies", String(Math.min(line.qty, 4)));
  return tile;
}

/** A line's ⋯ menu: a short Play-now line's stand-ins (editor-swaps.js), its printing,
 * moving it to another section, and Remove (last). */
function rowMenuButton(line) {
  const uid = line.uid;
  const button = el("button", { type: "button", class: "btn btn-quiet edit-more", "data-focus": `more:${uid}`,
    "aria-label": `More for ${line.name}`, "aria-haspopup": "menu", text: "⋯",
    onclick: () => {
      const found = findLine(uid);
      if (!found) return;
      openMenu(button, [
        swapsAvailableFor(found.line) ? { text: "Stand-ins…", onclick: () => openSwapSheet(uid) } : null,
        { text: "Change printing…", onclick: () => openPrintings(uid) },
        ...moveTargets(found.section).map((s) => ({ text: `Move to ${moveWords(s)}`, onclick: () => moveLine(uid, s) })),
        "-",
        { text: "Remove", danger: true, onclick: () => removeLine(uid) }]);
    } });
  return button;
}

/** The sections a line in section may move to. */
function moveTargets(section) {
  return editor.sections.filter((s) => s !== section && (s !== "Commander" || currentKind() === "commander"));
}

function moveWords(section) {
  return section === "Commander" ? "the Commander section" : `the ${sectionWords(section)}`;
}

/** A removed line, where it was: "Removed 2 Llanowar Elves (FDN 227). Undo". */
function removedRow(g) {
  const line = g.line;
  const what = `${line.qty} ${line.name}` + (line.set ? ` (${printingText(line)})` : "");
  return el(visualLook() ? "div" : "li", { class: "edit-row edit-removed", "data-removed": g.uid },
    el("p", { class: "removed-text" }, el("span", { class: "removed-word", text: "Removed" }), ` ${what}`),
    el("button", { type: "button", class: "btn btn-quiet undo-btn", "data-focus": `undo:${g.uid}`,
      "aria-label": `Undo: put ${what} back`, onclick: () => undoRemove(g.uid) }, "Undo"));
}

/** "3" -> 3; anything but one or two digits -> NaN. */
function typedQty(text) {
  return /^\s*\d{1,2}\s*$/.test(text) ? parseInt(text, 10) : NaN;
}

/** − n +. "−" on a line of 1 removes it (with Undo, where it was). */
function stepper(line, where) {
  const uid = line.uid;
  const qty = el("input", { class: "qty-input", type: "text", inputmode: "numeric", pattern: "[0-9]*", maxlength: 2,
    value: String(line.qty), "aria-label": `Copies of ${line.name}`, "data-focus": `qty:${where}:${uid}`,
    enterkeyhint: "done" });
  qty.addEventListener("focus", () => qty.select());
  // A number counts as it's typed (the count, the draft, the checks) and nothing is drawn again: the
  // tap that comes next, on Save or on another row's +, lands on what the finger went for.
  qty.addEventListener("input", () => {
    const n = typedQty(qty.value);
    if (n >= 1) setQty(uid, n);
  });
  // Leaving the box: 0 removes the line, anything that isn't a number goes back to the count.
  qty.addEventListener("change", () => {
    const found = findLine(uid);
    if (!found) return;
    const n = typedQty(qty.value);
    if (n === 0) {
      removeLine(uid);
      return;
    }
    if (n >= 1 && n !== found.line.qty) setQty(uid, n);
    qty.value = String(found.line.qty);
  });
  qty.addEventListener("keydown", (e) => { if (e.key === "Enter") qty.blur(); });
  return el("div", { class: "stepper edit-stepper", "data-uid": uid },
    el("button", { type: "button", class: "step step-minus", "aria-label": line.qty <= 1 ? `Remove ${line.name}` : `One fewer ${line.name}`,
      "data-focus": `minus:${where}:${uid}`, onclick: () => stepQty(uid, -1) }, "−"),
    qty,
    el("button", { type: "button", class: "step step-plus", "aria-label": `One more ${line.name}`, disabled: line.qty >= MAX_COPIES || null,
      "data-focus": `plus:${where}:${uid}`, onclick: () => stepQty(uid, 1) }, "+"));
}

function stepQty(uid, by) {
  const found = findLine(uid);
  if (!found) return;
  if (found.line.qty + by < 1) { removeLine(uid); return; }
  setQty(uid, found.line.qty + by);
}

function setQty(uid, n) {
  const found = findLine(uid);
  if (!found) return;
  const qty = Math.max(1, Math.min(MAX_COPIES, n));
  if (qty === found.line.qty) return;
  found.line.qty = qty;
  showQty(found.line);
  changed({ list: false });
}

/** A line's copies changed: its steppers, its picture stack and the counts follow, in place. A box being
 * typed in keeps what's typed. */
function showQty(line) {
  for (const box of document.querySelectorAll(`#main .stepper[data-uid="${line.uid}"]`)) {
    const input = box.querySelector(".qty-input");
    const typing = input === document.activeElement && typedQty(input.value) === line.qty;
    if (!typing && input.value !== String(line.qty)) input.value = String(line.qty);
    const minus = box.querySelector(".step-minus");
    minus.setAttribute("aria-label", line.qty <= 1 ? `Remove ${line.name}` : `One fewer ${line.name}`);
    const plusButton = box.querySelector(".step-plus");
    const off = line.qty >= MAX_COPIES;
    // A button that goes grey while it has the focus hands it to the box, so the keys still work.
    if (off && plusButton === document.activeElement) input.focus({ preventScroll: true });
    plusButton.disabled = off;
  }
  const tile = editor.dom.lines && editor.dom.lines.querySelector(`.edit-tile[data-uid="${line.uid}"]`);
  if (tile) {
    tile.setAttribute("data-copies", String(Math.min(line.qty, 4)));
    const badge = tile.querySelector(".card-tile-qty");
    if (badge) badge.textContent = `×${line.qty}`;
    else if (line.qty > 1) tile.querySelector(".card-tile-pic").append(el("span", { class: "card-tile-qty", text: `×${line.qty}` }));
    if (badge && line.qty <= 1) badge.remove();
  }
  refreshCounts();
}

function removeLine(uid) {
  const ed = editor;
  const found = findLine(uid);
  if (!found) return;
  const { line, section, index } = found;
  const lines = ed.lists[section];
  // Undo puts it back where it was in the file: before the lines that came after it, else after the
  // ones before it.
  const gone = { uid, line, section, before: lines.slice(0, index).map((l) => l.uid),
    after: lines.slice(index + 1).map((l) => l.uid) };
  lines.splice(index, 1);
  ed.removed.push(gone);
  if (ed.lastAdded === uid) ed.lastAdded = null;
  // The row becomes "Removed ... Undo" at the same height, so the rows under the finger don't move up
  // (a quick second tap doesn't remove the next card too).
  const row = ed.dom.lines && ed.dom.lines.querySelector(`.edit-row[data-uid="${uid}"]`);
  if (row) {
    const active = document.activeElement;
    const hadFocus = !active || active === document.body || row.contains(active);
    const stub = removedRow(gone);
    stub.style.minHeight = `${Math.round(row.getBoundingClientRect().height)}px`;
    row.replaceWith(stub);
    if (hadFocus) stub.querySelector("button").focus({ preventScroll: true });
    refreshCounts();
  } else {
    drawLines();
  }
  changed({ list: false });
}

function undoRemove(uid) {
  const ed = editor;
  const i = ed.removed.findIndex((g) => g.uid === uid);
  if (i < 0) return;
  const [g] = ed.removed.splice(i, 1);
  const lines = ed.lists[g.section] || (ed.lists[g.section] = []);
  const same = lines.find((l) => lineKey(l) === lineKey(g.line));
  if (same) {
    same.qty = Math.min(MAX_COPIES, same.qty + g.line.qty);
  } else {
    let at = lines.findIndex((l) => g.after.includes(l.uid));
    if (at < 0) {
      const before = lines.map((l) => g.before.includes(l.uid)).lastIndexOf(true);
      at = before < 0 ? 0 : before + 1;
    }
    lines.splice(at, 0, g.line);
  }
  syncSections();
  const stub = ed.dom.lines && ed.dom.lines.querySelector(`[data-removed="${uid}"]`);
  const hadFocus = stub && stub.contains(document.activeElement);
  if (stub && !same) {
    const row = visualLook() ? lineTile(g.line, g.section) : lineRow(g.line, g.section);
    stub.replaceWith(row);
    if (hadFocus) row.querySelector(".step-plus").focus({ preventScroll: true });
    refreshCounts();
    markRows();
    showRowAvailability(currentAvailability());
  } else if (stub) {
    stub.remove();
    showQty(same);
  } else {
    drawLines();
  }
  changed({ list: false });
  if (same) toast(`${g.line.name}: back on its line, ${plural(same.qty, "copy", "copies")} now.`);
}

/** Move a line to another section (the 99 and the Commander section, the deck and the sideboard). */
function moveLine(uid, to) {
  const ed = editor;
  const found = findLine(uid);
  if (!found) return;
  const { line, section, index } = found;
  ed.lists[section].splice(index, 1);
  const into = ed.lists[to] || (ed.lists[to] = []);
  const same = into.find((l) => lineKey(l) === lineKey(line));
  if (same) same.qty = Math.min(MAX_COPIES, same.qty + line.qty);
  else placeLine(into, line);
  const shown = same || line;
  ed.flash = shown.uid;
  syncSections();
  if (ed.dom.addTo) drawAddTo();
  changed();
  const row = ed.dom.lines.querySelector(`.edit-row[data-uid="${shown.uid}"]`);
  if (row) {
    row.scrollIntoView({ block: "center" });
    const chip = row.querySelector(".chip-btn") || row.querySelector("button");
    if (chip) chip.focus({ preventScroll: true });
  }
  toast(`${line.name} is in ${moveWords(to)} now.`);
}
