/* Printings in box (lib/decks/printings.py): which physical printing of a built deck's cards went in
 * its box. The deck page's Cards tab shows the record and its sheet (POST /api/deck/printings); Build
 * decks' pull tiles and big view ask "Which printing?" and Finish building writes the choices. A record reserves
 * nothing: cards are still counted by name. */
"use strict";

/** "FDN 227 ×2 · M19 314 foil ×2": the printings chosen for one card. */
function boxPrintingWords(chosen) {
  return chosen.filter((c) => c.quantity > 0).map((c) => `${c.label} ×${c.quantity}`).join(" · ");
}

/** The deck page's Printings in box part, for a built home deck whose viewer sees the collection. */
function deckPrintingsSection(data) {
  const info = data.printings_in_box;
  if (!info) return null;
  const section = el("section", { class: "deck-section deck-printings", id: "sec-printings", "aria-labelledby": "h-printings" },
    el("h2", { id: "h-printings", text: "Printings in box" }));
  const byName = new Map();
  for (const line of info.recorded || []) {
    if (!byName.has(line.name)) byName.set(line.name, []);
    byName.get(line.name).push(line);
  }
  if (byName.size) {
    section.append(el("ul", { class: "pack-plain deck-printings-list" }, [...byName].map(([name, lines]) =>
      el("li", {}, el("span", { class: "deck-printings-name", text: name }), " ",
        el("span", { class: "sub", text: boxPrintingWords(lines) })))));
  } else {
    section.append(el("p", { class: "sub", text: "Not recorded yet. Build decks asks which printing you pull, or record it here." }));
  }
  if ((info.stale || []).length) {
    add(section, [warningsBox(info.stale, "Printings in box out of date"),
      el("p", { class: "sub", text: "These parts are ignored until they're put right." })]);
  }
  if (info.editable && (info.cards || []).some((c) => c.options.length)) {
    section.append(el("button", { type: "button", class: "btn btn-quiet", text: "Printings in box…",
      onclick: () => openDeckPrintings(data) }));
  }
  return section;
}

/** A count per printing of each card the box holds, at most the copies the box holds and other decks'
 * records leave. Saved as one change; a card left at 0 isn't recorded. */
function openDeckPrintings(data) {
  const info = data.printings_in_box, s = data.summary;
  const sheet = openSheet({ title: "Printings in box", wide: true });
  const groups = [];
  sheet.body.append(el("p", { class: "sub", text: "Which printing of each card is in this deck's box. "
    + "Leave a card at 0 when you don't know." }));
  const list = el("ul", { class: "pack-plain deck-printings-choices" });
  for (const card of info.cards || []) {
    if (!card.options.length) continue;
    const inputs = card.options.map((option, index) => {
      const id = `printing-${sheet.heading.id}-${groups.length}-${index}`;
      const max = Math.min(card.held, option.free);
      const input = el("input", { id, type: "number", inputmode: "numeric", min: 0, max, step: 1,
        value: String(Math.min(option.recorded, max)) });
      const rest = option.free ? `${num(option.free)} not in other boxes` : "all in other boxes";
      return { option, input, max, node: el("span", { class: "deck-printing-choice" },
        el("label", { for: id, text: `${option.label} (${rest})` }), " ", input) };
    });
    groups.push({ card, inputs });
    list.append(el("li", {}, el("span", { class: "deck-printings-name", text: `${card.name}: ${plural(card.held, "copy", "copies")} in the box` }),
      ...inputs.map((i) => i.node)));
  }
  const message = el("p", { class: "box box-crit", hidden: true, role: "alert" });
  sheet.body.append(list, message);
  const fail = (text, input) => { message.textContent = text; message.hidden = false; if (input) input.focus(); };
  const save = () => {
    const cards = [];
    for (const { card, inputs } of groups) {
      let total = 0;
      for (const { option, input, max } of inputs) {
        const n = Number(input.value || 0);
        if (!Number.isInteger(n) || n < 0 || n > max) return fail(`Choose 0 to ${max} for ${card.name} ${option.label}.`, input);
        total += n;
        if (n) cards.push({ name: card.name, set: option.set, collector_number: option.collector_number,
          finish: option.finish, quantity: n });
      }
      if (total > card.held) return fail(`The box holds ${card.held} ${card.name}, not ${total}.`, inputs[0].input);
    }
    apiWrite("/api/deck/printings", { id: s.id, expect: info.expect, cards })
      .then(() => {
        sheet.close();
        toast("Printings in box saved");
        const here = parseHash();
        if (here.path === "deck" && addressDeckId(here.params.get("id") || "") === s.id) route();
      })
      .catch((e) => {
        if (!(e instanceof ApiError)) throw e;
        fail(e.message);
      });
  };
  sheetActions(sheet, [{ text: "Cancel", onclick: () => sheet.close() },
    { text: "Save", kind: "primary", value: "save", onclick: save }]);
  return sheet;
}

/** Build decks' chosen printings: view.boxPrintings[deck id][card name] = [{label, set, collector_number,
 * finish, quantity}]. Kept only while the plan's offers still include them, and within what qty (the copies
 * the plan pulls now) and each printing's free copies allow. */
function packPrintingPicks(view, deck, name, qty) {
  const offered = deck.printing_choices?.[name];
  if (!offered) return null;
  view.boxPrintings = view.boxPrintings || {};
  const picks = view.boxPrintings[deck.id] = view.boxPrintings[deck.id] || {};
  const option = (pick) => offered.options.find((o) => o.set === pick.set
    && o.collector_number === pick.collector_number && o.finish === pick.finish);
  if (picks[name] && !picks[name].every(option)) delete picks[name];
  if (picks[name]) {
    let room = qty;
    picks[name] = picks[name].map((pick) => {
      const quantity = Math.min(pick.quantity, option(pick).free, room);
      room -= quantity;
      return { ...pick, quantity };
    }).filter((pick) => pick.quantity > 0);
  }
  return { offered, picks };
}

/** "Foundations · FDN 227": a printing in words, its set's name when the server has it. */
function packPrintingName(option) {
  return option.set_name ? `${option.set_name} · ${option.label}` : option.label;
}

/** Draws one "Which printing?" control from the picks, in place. Options are only rebuilt when they've changed,
 * as this runs on every poll under an open viewer and a rebuild would shut a picker in use. */
function packPrintingDraw(view, control) {
  const { deck, name, qty, select, note } = control;
  const found = packPrintingPicks(view, deck, name, qty);
  if (!found) return;
  const { options } = found.offered, chosen = found.picks[name] || [];
  const total = chosen.reduce((n, c) => n + c.quantity, 0);
  const left = total && total < qty ? `${qty - total} not recorded` : "";
  if (!select) {
    control.node.textContent = left ? `${boxPrintingWords(chosen)} \u00b7 ${left}`
      : `${packPrintingName(chosen[0])} (only printing in storage)`;
    return;
  }
  const index = chosen.length === 1 ? options.findIndex((o) => o.set === chosen[0].set
    && o.collector_number === chosen[0].collector_number && o.finish === chosen[0].finish) : -1;
  const whole = index >= 0 && chosen[0].quantity === Math.min(qty, options[index].free);
  control.wanted = !chosen.length ? "" : whole ? String(index) : "made";
  const items = [["", "Which printing?"],
    ...options.map((o, i) => [String(i), `${packPrintingName(o)} (${num(o.free)} free)`]),
    control.wanted === "made" ? ["made", boxPrintingWords(chosen), true] : null,
    qty > 1 && options.length > 1 ? ["split", "Split between printings\u2026"] : null].filter(Boolean);
  const key = JSON.stringify(items);
  if (control.items !== key) {
    control.items = key;
    clear(select).append(...items.map(([value, text, disabled]) => el("option", { value, text, disabled })));
  }
  if (select.value !== control.wanted) select.value = control.wanted;
  select.classList.toggle("is-chosen", total > 0);
  note.textContent = left;
  note.hidden = !left;
}

/** One card's "Which printing?": plain words when storage can hold only one printing (it's certain, so it's
 * filled in), else a native select. {deck, name, qty, node, select, note}, or null when nothing's offered. */
function packPrintingMake(view, deck, name, qty) {
  const found = packPrintingPicks(view, deck, name, qty);
  if (!found) return null;
  const { offered, picks } = found;
  const control = { deck, name, qty, select: null, note: null, wanted: "", items: null };
  if (offered.only) {
    picks[name] = [{ ...offered.only, quantity: Math.min(qty, offered.only.free), only: true }];
    control.node = el("p", { class: "pack-printing is-chosen" });
  } else {
    control.select = el("select", { class: "pack-printing-select", "aria-label": `${name}: which printing`,
      onchange: () => packPrintingChosen(view, control) });
    control.note = el("span", { class: "pack-printing-note", hidden: true });
    control.node = el("div", { class: "pack-printing" }, control.select, control.note);
  }
  packPrintingDraw(view, control);
  return control;
}

/** A pull tile's control, kept in the plan's list for the big view to find. */
function packPrintingControl(view, deck, name, qty) {
  const control = packPrintingMake(view, deck, name, qty);
  if (!control) return null;
  (view.printingControls ||= []).push(control);
  return control.node;
}

/** The current plan's tile control of a card, or null. */
function packPrintingListed(view, deckId, name) {
  return (view.printingControls || []).find((c) => c.deck.id === deckId && c.name === name
    && view.data?.decks.includes(c.deck)) || null;
}

/** A pick changed: every control of that card follows in place, and the plan isn't drawn again (nothing else
 * shows it), so the scroll and the focus stay put. */
function packPrintingRefresh(view, deckId, name) {
  const tile = packPrintingListed(view, deckId, name);
  if (tile) packPrintingDraw(view, tile);
  packViewerSync(view);
}

/** The select's answer. A printing takes all the copies pulled, up to its free ones; Split opens the sheet. */
function packPrintingChosen(view, control) {
  const { deck, name, qty, select } = control, value = select.value;
  const found = assemblyActive(view) && !view.saving && view.data?.decks.includes(deck)
    ? packPrintingPicks(view, deck, name, qty) : null;
  if (!found || value === "split" || value === "made") select.value = control.wanted;
  if (!found || value === "made") return;
  if (value === "split") { openPackPrinting(view, deck, name, qty); return; }
  const option = value === "" ? null : found.offered.options[Number(value)];
  found.picks[name] = option ? [{ ...option, quantity: Math.min(qty, option.free) }] : [];
  packPrintingRefresh(view, deck.id, name);
}

function openPackPrinting(view, deck, name, qty) {
  const found = packPrintingPicks(view, deck, name, qty);
  if (!found) return null;
  const { offered, picks } = found;
  const ctx = openAssemblySheet(view, `Which printing of ${name}?`);
  const current = picks[name] || [];
  const inputs = offered.options.map((option, index) => {
    const id = `pack-printing-${ctx.sheet.heading.id}-${index}`;
    const max = Math.min(qty, option.free);
    const was = current.find((c) => c.set === option.set && c.collector_number === option.collector_number
      && c.finish === option.finish);
    const input = el("input", { id, type: "number", inputmode: "numeric", min: 0, max, step: 1,
      value: String(was ? Math.min(was.quantity, max) : 0) });
    return { option, input, max, node: el("li", {}, el("label", { for: id, text: `${option.label} (${num(option.free)} not in other boxes)` }), " ", input) };
  });
  const error = el("p", { class: "form-error", role: "alert" });
  ctx.sheet.body.append(el("p", { text: `You're pulling ${plural(qty, "copy", "copies")} for ${deck.title}. `
    + "Say how many of each printing went in, or leave them at 0 to skip: nothing waits on this." }),
    el("ul", { class: "pack-plain pack-printing-choices" }, inputs.map((i) => i.node)), error);
  const keep = () => {
    if (!assemblySheetHere(ctx)) return;
    const chosen = [];
    let total = 0;
    for (const { option, input, max } of inputs) {
      const n = Number(input.value || 0);
      if (!Number.isInteger(n) || n < 0 || n > max) { error.textContent = `Choose 0 to ${max} for ${option.label}.`; input.focus(); return; }
      total += n;
      if (n) chosen.push({ ...option, quantity: n });
    }
    if (total > qty) { error.textContent = `You're pulling ${qty}, not ${total}.`; inputs[0].input.focus(); return; }
    if (chosen.length) picks[name] = chosen; else picks[name] = [];
    ctx.sheet.close();
    packPrintingRefresh(view, deck.id, name);
  };
  sheetActions(ctx.sheet, [{ text: "Done", kind: "primary", onclick: keep }, { text: "Cancel", onclick: () => ctx.sheet.close() }]);
  return ctx;
}

/** Finish building's printings: {deck id: [{name, set, collector_number, finish, quantity}]} of the decks it
 * marks built. */
function packPrintingsBody(view, data) {
  const ids = new Set((data.completion?.decks || []).map((d) => d.id)), out = {};
  for (const [id, cards] of Object.entries(view.boxPrintings || {})) {
    if (!ids.has(id)) continue;
    const deck = data.decks.find((d) => d.id === id);
    const rows = [];
    for (const [name, chosen] of Object.entries(cards)) {
      if (!deck?.printing_choices?.[name]) continue;
      for (const c of chosen) if (c.quantity > 0) rows.push({ name, set: c.set, collector_number: c.collector_number,
        finish: c.finish, quantity: c.quantity });
    }
    if (rows.length) out[id] = rows;
  }
  return out;
}
