/* The deck's Considering list (E2-S23, lib/decks/considering.py): cards that might go in, kept with the
 * deck outside its Planned and Play-now lists, so they're never needed, missing or in use. The Cards tab
 * lists them, each saying whether a copy is free in the pool (only to a viewer who sees the space's
 * collection: the server sends "free" to no one else). Whoever may change the deck adds a card, takes one
 * off, or moves one into the Planned list (POST /api/deck/considering: one save of the deck). */
"use strict";

/** "Free in the pool", "1 of 2 free", "None free" (with copies on the way said), or null when the viewer
 * doesn't see the collection. A basic land is always to hand. */
function consideringFreeWords(line) {
  if (!("free" in line)) return null;
  if (line.free === null) return "Basic land";
  const coming = line.on_the_way ? ` (${num(line.on_the_way)} on the way)` : "";
  if (line.free >= line.qty) return `Free in the pool${coming}`;
  if (line.free > 0) return `${num(line.free)} of ${num(line.qty)} free${coming}`;
  return "None free";
}

/** The Cards tab's Considering part: null for a product, a pairing, or an empty list nobody here may fill. */
function deckConsideringSection(data) {
  const info = data.considering;
  const s = data.summary;
  if (!info || !Array.isArray(info.lines)) return null;
  const editable = !s.read_only && canEditDeck(s) && data.version === "target";
  if (!info.lines.length && !editable) return null;
  const section = el("section", { class: "deck-section deck-considering", id: "sec-considering",
    "aria-labelledby": "h-considering" }, el("h2", { id: "h-considering", text: "Considering" }));
  const token = routeToken, profile = state.profile?.id;
  const here = () => token === routeToken && profile === state.profile?.id;
  const add = editable ? el("button", { type: "button", class: "btn btn-quiet", text: "Add a card to consider…",
    onclick: () => { if (here()) openConsideringAdd(data); } }) : null;
  if (!info.lines.length) {
    section.append(emptyBox("No cards being considered. They stay with the deck without counting in its lists.", add));
    return section;
  }
  section.append(el("p", { class: "sub", text: "Cards that might go in. They don't count in the lists, the table or packing." }),
    el("div", {}, info.lines.map((line, index) => {
      const free = consideringFreeWords(line);
      const row = cardRow(line.card, { qty: line.qty, name: line.name,
        meta: free === null ? undefined : free, unknownMeta: free || "Not a card Deck Lab knows",
        viewerGroup: "deck-considering", caption: `${line.qty} x ${line.name}` });
      if (!editable) return row;
      const actions = menuButton("⋯", [
        { label: "Move to the Planned list", onclick: () => saveConsidering(data, { action: "move", index }) },
        { label: "Move to the sideboard", onclick: () => saveConsidering(data, { action: "move", index, section: "Sideboard" }) },
        "sep",
        { label: "Remove", danger: true, onclick: () => removeConsidering(data, index) },
      ], { aria: `${line.name}: move or remove`, buttonClass: "btn btn-quiet" });
      return el("div", { class: "deck-considering-row" }, row, actions);
    })),
    add);
  return section;
}

/** One change to the Considering list, saved with the deck; the page is drawn again from the saved deck. A
 * move, or a save with warnings or other decks' tables now out of date, gets the deck page's box about the
 * save (editor-deckpage.js savedBox: the "Decklist changed" mark, the table, the warnings and Update their
 * tables); anything else a toast. Returns the save's answer, or false when it was refused. */
async function saveConsidering(data, change, onError = null) {
  const id = data.summary.id;
  try {
    const answer = await apiWrite("/api/deck/considering", { id, sha256: data.considering.sha256, ...change });
    state.library = null;
    const here = parseHash();
    const onDeck = here.path === "deck" && addressDeckId(here.params.get("id") || "") === id;
    if (change.action === "move" || answer?.warnings?.length || answer?.stale_tables?.length) {
      toast("");                      // an older note would cover the box about the save
      if (onDeck) state.saved = { hash: location.hash, profile: state.profile?.id, answer };
    } else if (change.action === "add") toast("Added to Considering.");
    if (onDeck) route();
    return answer || true;
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    if (onError) onError(e.message + (e.status === 409 ? " Reload the deck, then try again." : ""));
    else toast(e.message);
    return false;
  }
}

/** Remove takes the line off at once, with an Undo toast that adds it back (at the end of the list) in
 * another save, from the saved deck's sha. */
async function removeConsidering(data, index) {
  const line = data.considering.lines[index];
  const answer = await saveConsidering(data, { action: "remove", index });
  if (!answer || !line) return;
  const back = { name: line.name, qty: line.qty, set: line.set, number: line.number, finish: line.finish };
  showToast(`Took ${line.name} off Considering.`, { undo: () => {
    if (typeof answer.sha256 !== "string") { toast("Reload the deck to add it back."); return; }
    saveConsidering({ summary: data.summary, considering: { sha256: answer.sha256 } }, { action: "add", line: back });
  } });
}

/** A card name and how many copies, added to the Considering list (the server checks the name). */
function openConsideringAdd(data) {
  const sheet = openSheet("Add a card to consider");
  const nameId = `consider-name-${sheet.heading.id}`, qtyId = `consider-qty-${sheet.heading.id}`;
  const name = el("input", { id: nameId, type: "text", autocomplete: "off", required: true });
  const qty = el("input", { id: qtyId, type: "number", inputmode: "numeric", min: 1, max: 99, step: 1, value: "1" });
  const message = el("p", { class: "form-error", role: "alert" });
  sheet.body.append(el("label", { for: nameId, text: "Card name" }), name,
    el("label", { for: qtyId, text: "Copies" }), qty, message);
  const save = async () => {
    const n = Number(qty.value || 0);
    if (!name.value.trim()) { message.textContent = "Type a card's name."; name.focus(); return; }
    if (!Number.isInteger(n) || n < 1 || n > 99) { message.textContent = "Choose 1 to 99 copies."; qty.focus(); return; }
    message.textContent = "";
    const done = await saveConsidering(data, { action: "add", line: { name: name.value.trim(), qty: n } },
      (text) => { message.textContent = text; });
    if (done) sheet.close();
  };
  sheetActions(sheet, [{ text: "Cancel", onclick: () => sheet.close() },
    { text: "Add", kind: "primary", value: "save", onclick: save }]);
  return sheet;
}
