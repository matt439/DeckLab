/* Dice and counters (E7-S24): the Tokens page's panel listing a space's owned dice and counters, kept apart
 * from its token cards, with an add/edit sheet for the space's token editors (GET /api/dice, POST
 * /api/dice/save), and the deck page's words for whether they cover a need (tokenCountersPart's cover).
 * Loaded after tokens.js and tokens-edit.js, whose page state (view, tokensActive) it reads. */
"use strict";

const DICE_SIZES = ["d4", "d6", "d8", "d10", "d12", "d20", "spindown"];
const DICE_SIZE_WORDS = { spindown: "Spindown (d20)" };
const DICE_COVER_CHIPS = { named: ["good", "Covered"], generic: ["info", "Any-kind stands in"],
  none: ["warn", "Not covered"] };

/** The dice API's address for a space: home's has no ?space=. */
function dicePath(space) {
  return !space || space === HOME_SPACE ? "/api/dice" : `/api/dice?space=${encodeURIComponent(space)}`;
}

/** "d20 (red)", "poison counter", "counter (any kind)": a row as the panel names it. */
function diceLabel(row) {
  const words = row.type === "die" ? (row.size === "spindown" ? "spindown d20" : row.size || "die")
    : row.kind ? `${row.kind} counter` : "counter (any kind)";
  return row.design ? `${words}, ${row.design}` : words;
}

/** The deck page's chip for a counter need's cover (dice_cover.py's state). */
function diceCoverChip(cover) {
  if (!cover || !DICE_COVER_CHIPS[cover.state]) return null;
  const [kind, words] = DICE_COVER_CHIPS[cover.state];
  return el("span", { class: `status status-${kind} dice-cover dice-cover-${cover.state}`, text: words });
}

/** The Tokens page's Dice and counters panel, loaded on its own so the token cards never wait for it. Returns the
 * panel's section; view: the Tokens page's (space, canEdit, profile, token). */
function diceTokensPanel(view) {
  const box = { view, data: null, busy: false, seq: 0 };
  box.list = el("div", { class: "dice-list" });
  box.message = el("div", { class: "dice-message", role: "status", "aria-live": "polite" });
  box.add = view.canEdit ? el("button", { type: "button", class: "btn dice-mutate", text: "Add a die or counter",
    onclick: () => openDiceSheet(box) }) : null;
  box.root = el("section", { class: "panel dice-panel", "aria-labelledby": "dice-title" },
    el("div", { class: "dice-head" }, el("h2", { id: "dice-title", text: "Dice and counters" }), box.add),
    el("p", { class: "sub", text: "Owned dice and counters, apart from the token cards. A die or a counter with no kind stands for any kind on the deck pages." }),
    box.message, box.list);
  box.list.append(loadingBox("Loading dice and counters…", { small: true }));
  loadDice(box);
  return box.root;
}

function diceActive(box) {
  return box.root.isConnected && tokensActive(box.view);
}

async function loadDice(box) {
  const seq = ++box.seq;
  try {
    const data = await api(dicePath(box.view.space));
    if (seq !== box.seq) return;
    drawDice(box, data);
  } catch (error) {
    if (seq !== box.seq) return;
    clear(box.list).append(loadFailed("The dice and counters", error, () => loadDice(box)));
    if (box.add) box.add.disabled = true;
  }
}

function drawDice(box, data) {
  box.data = data;
  const rows = data.rows || [];
  if (box.add) box.add.disabled = !data.ready || box.busy;
  clear(box.list);
  if (!data.ready) {
    box.list.append(el("p", { class: "box box-info dice-not-ready",
      text: "Dice and counters can't be recorded yet: Deck Lab's database needs an update first (migration 0020, on the PC). The token cards work as before." }));
    return;
  }
  add(box.list, [warningsBox(data.problems, "Some dice or counters can't be read")]);
  if (!rows.length) {
    box.list.append(emptyBox("No dice or counters recorded yet."));
    return;
  }
  box.list.append(el("p", { class: "result-count", text: `${plural(rows.length, "kind")}, ${plural(data.items || 0, "item")}` }),
    el("ul", { class: "dice-rows" }, rows.map((row) => el("li", { class: "dice-row", "data-key": row.key },
      el("span", { class: "dice-row-name" }, el("b", { text: diceLabel(row) }), ` ×${num(row.quantity)}`,
        row.notes ? el("small", { class: "sub", text: ` · ${row.notes}` }) : null),
      box.view.canEdit ? el("button", { type: "button", class: "btn btn-quiet dice-mutate", text: "Edit",
        "aria-label": `Edit ${diceLabel(row)}`, onclick: () => openDiceSheet(box, row) }) : null))));
}

function setDiceBusy(box, busyNow) {
  box.busy = busyNow;
  for (const control of box.root.querySelectorAll(".dice-mutate")) control.disabled = busyNow || !(box.data && box.data.ready);
}

/** The six values the server names a row by. */
function diceBase(row) {
  return { type: row.type, size: row.size, kind: row.kind, design: row.design, quantity: String(row.quantity), notes: row.notes };
}

/** Add a die or counter, or edit one ({row}: a GET row), in a sheet. */
function openDiceSheet(box, row = null) {
  if (!diceActive(box) || box.busy || !box.data || !box.data.ready) return null;
  const editing = Boolean(row);
  const sheet = openSheet(editing ? diceLabel(row) : "Add a die or counter");
  const id = (key) => `dice-${key}-${sheet.heading.id}`;
  const message = el("div", { class: "dice-sheet-message", role: "status", "aria-live": "polite" });
  const type = el("select", { id: id("type") }, [["die", "Die"], ["counter", "Counter"]].map(([value, text]) =>
    el("option", { value, text, selected: (row ? row.type : "die") === value || null })));
  const size = el("select", { id: id("size") }, DICE_SIZES.map((value) =>
    el("option", { value, text: DICE_SIZE_WORDS[value] || value, selected: (row ? row.size : "d6") === value || null })));
  const kind = el("input", { id: id("kind"), type: "text", maxlength: 30, autocomplete: "off", value: row ? row.kind : "",
    placeholder: "+1/+1, poison, loyalty… (blank: any kind)" });
  const design = el("input", { id: id("design"), type: "text", maxlength: 60, autocomplete: "off", value: row ? row.design : "",
    placeholder: "e.g. red, glass beads" });
  const quantity = el("input", { id: id("quantity"), type: "number", min: 0, max: 9999, step: 1, inputmode: "numeric",
    value: row ? String(row.quantity) : "1" });
  const notes = el("input", { id: id("notes"), type: "text", maxlength: 200, autocomplete: "off", value: row ? row.notes : "" });
  const field = (input, words) => el("label", { class: "field", for: input.id }, el("span", { text: words }), input);
  const sizeField = field(size, "Size");
  const kindField = field(kind, "Counter kind");
  const show = () => { sizeField.hidden = type.value !== "die"; kindField.hidden = type.value !== "counter"; };
  type.addEventListener("change", show);
  show();
  const form = el("form", { class: "dice-form", novalidate: true, onsubmit: (event) => { event.preventDefault(); save(); } },
    message, field(type, "Type"), sizeField, kindField, field(design, "Colour or design"), field(quantity, "Quantity"),
    field(notes, "Notes"));
  sheet.body.append(form);
  const values = () => ({ type: type.value, size: type.value === "die" ? size.value : "",
    kind: type.value === "counter" ? kind.value.trim() : "", design: design.value.trim(),
    quantity: quantity.value.trim(), notes: notes.value.trim() });
  async function save() {
    if (box.busy) return;
    const body = { action: editing ? "edit" : "add", sha256: box.data.sha256, row: values() };
    if (editing) body.base = diceBase(row);
    await diceWrite(box, body, sheet, message, editing ? "Saved." : "Added.");
  }
  sheetActions(sheet, [
    editing ? null : { text: "Cancel", value: "cancel", onclick: () => sheet.close() },
    { text: "Save", kind: "primary", value: "save", onclick: save },
    editing ? { text: "Remove…", kind: "danger btn-quiet", value: "remove", onclick: () => { sheet.close(); removeDice(box, row); } } : null]);
  return sheet;
}

async function removeDice(box, row) {
  if (!diceActive(box) || box.busy) return;
  const reason = await new Promise((resolve) => {
    const sheet = openSheet(`Remove ${diceLabel(row)} ×${row.quantity}?`, { onClose: (result) => resolve(result == null ? null : result) });
    const input = el("input", { id: `dice-reason-${sheet.heading.id}`, type: "text", maxlength: 200, autocomplete: "off",
      placeholder: "e.g. lost, traded" });
    sheet.body.append(el("p", { text: "For a partial loss, use Edit to lower the quantity (0 keeps the row)." }),
      el("label", { class: "field", for: input.id }, el("span", { text: "Reason (optional)" }), input));
    sheetActions(sheet, [
      { text: "Remove", kind: "danger", value: "remove", onclick: () => sheet.close({ reason: input.value.trim() }) },
      { text: "Keep it", value: "keep", onclick: () => sheet.close(null) }]);
  });
  if (!reason || !diceActive(box)) return;
  const body = { action: "remove", sha256: box.data.sha256, base: diceBase(row) };
  if (reason.reason) body.reason = reason.reason;
  await diceWrite(box, body, null, box.message, `${diceLabel(row)} removed.`);
}

/** POST one write; on success the panel shows the new list, on a conflict the list as it is now. */
async function diceWrite(box, body, sheet, message, done) {
  setDiceBusy(box, true);
  clear(message).append(loadingBox("Saving…", { small: true }));
  try {
    const space = box.view.space;
    const answer = await apiWrite("/api/dice/save", space && space !== HOME_SPACE ? { ...body, space } : body);
    if (sheet) sheet.close();
    if (!diceActive(box)) return;
    setDiceBusy(box, false);
    drawDice(box, answer.data);
    clear(box.message).append(el("p", { text: done }));
    toast(done);
  } catch (error) {
    setDiceBusy(box, false);
    const latest = error.data && error.data.latest;
    if (latest && diceActive(box)) drawDice(box, latest);
    clear(message).append(el("div", { class: "box box-crit" }, el("p", { text: error.message }),
      latest ? el("p", { text: "The list below is as it is now." }) : null));
  }
}
