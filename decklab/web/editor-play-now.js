/* Review a saved Commander's Play-now shortages before applying one local edit (E2-S34). */
"use strict";

function editorPlayNowSource(ed) {
  return noOwnedList() ? ed.view.lists.target : ed.lists;
}

function editorPlayNowButton(ed) {
  if (ed.mode !== "edit" || ed.version !== "owned" || ed.kind !== "commander" || ed.readOnly
    || !seesInventory(ed.space) || !editorPlayNowSource(ed)?.Commander?.length) return null;
  return el("button", { type: "button", class: noOwnedList() ? "btn btn-primary" : "btn",
    "aria-haspopup": "dialog", text: "Draft from free copies", onclick: openEditorPlayNow });
}

async function openEditorPlayNow() {
  const ed = editor;
  if (!ed || ed.readOnly || ed.saving || ed.leaving || !seesInventory(ed.space)) return;
  const startsFromPlanned = noOwnedList();
  const source = editorPlayNowSource(ed);
  const sha = ed.sha256, signature = listSignature(source), raw = sendList(source);
  const sheet = openSheet({ title: "Draft a Play-now list", wide: true });
  const owns = editorWriteOwner(ed, sheet);
  const remainsCurrent = () => ed.sha256 === sha && noOwnedList() === startsFromPlanned
    && signature === listSignature(editorPlayNowSource(ed));
  const locked = new Set();
  const stale = () => {
    clear(sheet.foot);
    clear(sheet.body).append(el("p", { role: "status", text: "The draft changed. Close this review and open a new one." }));
  };
  const ask = async () => {
    if (!owns()) return;
    if (!remainsCurrent()) { stale(); return; }
    clear(sheet.foot);
    clear(sheet.body).append(loadingBox("Checking for free copies…"));
    let answer;
    try {
      answer = await apiWrite("/api/deck/play-now/preview", { id: ed.id, sha256: sha, list: raw, locked: [...locked] });
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
      if (owns()) {
        if (!remainsCurrent()) stale();
        else clear(sheet.body).append(loadFailed("The Play-now draft", error, ask));
      }
      return;
    }
    if (!owns()) return;
    if (!remainsCurrent() || answer.sha256 !== sha || answer.deck_id !== ed.id) { stale(); return; }
    drawEditorPlayNow(sheet, answer, locked, ask, apply);

    function apply() {
      if (!owns() || ed.saving || !seesInventory(ed.space)) return;
      if (!remainsCurrent()) { stale(); return; }
      sheet.close();
      applyEditorPlayNow(ed, answer.rows);
    }
  };
  await ask();
}

function drawEditorPlayNow(sheet, answer, locked, ask, apply) {
  const rows = answer.rows;
  const filled = rows.reduce((n, row) => n + row.adds.length, 0);
  const stillShort = rows.reduce((n, row) => n + row.unfilled, 0);
  const needsReview = el("button", { type: "button", class: "btn", text: "Update preview", onclick: ask, hidden: true });
  const use = el("button", { type: "button", class: "btn btn-primary", text: "Use this draft", onclick: apply, disabled: !filled });
  const offeredLocks = new Set();
  const items = rows.map((row) => {
    let keep = null;
    if (row.replaceable && !offeredLocks.has(row.name)) {
      offeredLocks.add(row.name);
      const input = el("input", { type: "checkbox", onchange: () => {
        if (input.checked) locked.add(row.name);
        else locked.delete(row.name);
        needsReview.hidden = false;
        use.disabled = true;
      } });
      input.checked = locked.has(row.name);
      keep = el("label", {}, input, ` Keep ${row.name}`);
    }
    const matches = row.adds.map(({ line, note }) => el("li", {},
      el("strong", { text: line.name }), el("p", { class: "sub", text: note })));
    return el("li", { class: "play-now-row" },
      el("p", {}, el("strong", { text: row.name }), ` · ${row.section} · ${plural(row.missing, "copy short", "copies short")}`),
      matches.length ? el("ul", {}, matches) : null,
      row.unfilled ? el("p", { class: "sub", text: `${plural(row.unfilled, "copy still short", "copies still short")}`
        + (row.locked || !row.replaceable ? " (kept in the list)." : ".") }) : null, keep);
  });
  const bracket = answer.bracket;
  add(clear(sheet.body), [
    el("p", { text: rows.length ? `${plural(filled, "swap", "swaps")} proposed · ${plural(stillShort, "copy still short", "copies still short")}.`
      : "This list has no confirmed shortages." }),
    rows.length ? el("ul", { class: "swap-list" }, items) : null,
    el("h3", { text: "Commander checks" }),
    answer.checks.length ? el("ul", {}, answer.checks.map((text) => el("li", { text })))
      : el("p", { text: "No Commander rules warnings for this draft." }),
    bracket ? el("p", { class: "sub", text: `Minimum Bracket ${bracket.minimum}${bracket.target ? ` · Target ${bracket.target}` : ""}.` }) : null,
  ]);
  clear(sheet.foot).append(needsReview, ...(filled ? [use] : []));
}

function applyEditorPlayNow(ed, rows) {
  const starting = noOwnedList();
  const swaps = new Map(rows.filter((row) => row.adds.length).map((row) => [`${row.section}:${row.index}`, row]));
  if (!swaps.size) return;
  const notes = new Map();
  const source = starting ? copyList(editorPlayNowSource(ed)) : ed.lists;
  ed.lists = Object.fromEntries(Object.entries(source).map(([section, lines]) => [section,
    lines.flatMap((line, index) => {
      const row = swaps.get(`${section}:${index}`);
      if (!row) return [line];
      const rest = line.qty - row.adds.length;
      if (!notes.has(row.name)) notes.set(row.name, []);
      notes.get(row.name).push(...row.adds);
      return [...(rest ? [{ ...line, qty: rest }] : []), ...row.adds.map(({ line }) => newLine(line))];
    })]));
  ed.starting = ed.starting || starting;
  let text = ed.prose?.substitutes || "";
  const names = swapListNames(ed);
  const existing = text;
  for (const [outName, adds] of notes) {
    if (noteNaming(existing, outName, names)) continue;
    const inName = adds.map(({ line }) => line.name).join(", 1 ");
    const note = adds.length === 1 ? adds[0].note : adds.map(({ line, note }) => `${line.name}: ${note}`).join(" ");
    text = withSwapNote(text, { outQty: adds.length, outName, inQty: 1, inName, note });
  }
  if (text !== existing) ed.prose = { ...ed.prose, substitutes: text };
  syncSections();
  if (starting) drawEditor();
  changed({ list: !starting });
  const after = ed.snap;
  showToast("Play-now draft ready to check and save.", { undo: () => {
    if (editor === ed && ed.snap === after && undoLast()) toast("Play-now draft undone.");
  } });
}
