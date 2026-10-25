/* The intended list stays saved while the packing recipe chooses physical sideboard copies. */
"use strict";

function packSelectedChoice(item) {
  return { id: item.id, version: item.version,
    ...(item.sideboard != null ? { sideboard: { ...item.sideboard } } : {}) };
}

function packChooseVersion(view, picked, version, node = null) {
  if (node && !packScopeCurrent(view, picked, node)) return;
  if (picked.version === version) return;
  picked.version = version;
  delete picked.sideboard;
  view.sideboardChoosing?.delete(picked.id);
  packChanged(view);
}

function packScopeCurrent(view, picked, node) {
  return packChooserCanChange(view, node) && view.selected.includes(picked);
}

/** A recipe always includes the full main deck; sideboard quantities are an explicit final state. */
function packSideboardChoice(view, choice, picked) {
  if (String(choice.id).startsWith("product/") || String(choice.id).startsWith("pairing/")) return null;
  const rows = picked && choice.sideboards?.[picked.version];
  if (!rows?.length) return null;
  const intended = rows.reduce((sum, row) => sum + row.quantity, 0);
  const chosen = picked.sideboard;
  const custom = view.sideboardChoosing?.has(picked.id) || (chosen && Object.keys(chosen).length);
  const mode = custom ? "custom" : chosen ? "main" : "all";
  const select = el("select", { "aria-label": `${choice.title}: cards to assemble`,
    "data-pack-id": choice.id, "data-pack-control": "scope" },
    [["all", "Main deck + whole sideboard"], ["main", "Main deck only"], ["custom", "Choose sideboard cards"]]
      .map(([value, text]) => el("option", { value, text, selected: value === mode })));
  select.value = mode;
  const node = el("div", { class: "pack-sideboard-choice" },
    el("label", { class: "field" }, el("span", { text: "Cards to assemble" }), select));
  select.addEventListener("change", () => {
    if (!packScopeCurrent(view, picked, node)) return;
    view.sideboardChoosing ||= new Set();
    view.sideboardChoosing.delete(picked.id);
    if (select.value === "all") delete picked.sideboard;
    else if (select.value === "main") picked.sideboard = {};
    else {
      view.sideboardChoosing.add(picked.id);
      picked.sideboard = chosen ? { ...chosen } : Object.fromEntries(rows.map(row => [row.name, row.quantity]));
    }
    packChanged(view);
  });
  if (mode === "custom") {
    const fields = el("div", { class: "pack-sideboard-quantities" });
    const error = el("p", { class: "form-error", role: "alert" });
    for (const row of rows) {
      const qty = chosen?.[row.name] || 0;
      const input = el("input", { type: "number", min: 0, max: row.quantity, step: 1, value: qty,
        "data-pack-id": choice.id, "data-pack-control": `quantity:${row.name}`,
        "aria-label": `${choice.title}: ${row.name} sideboard copies` });
      input.addEventListener("change", () => {
        if (!packScopeCurrent(view, picked, node)) return;
        const value = String(input.value).trim(), number = Number(value);
        if (!/^\d+$/.test(value) || !Number.isSafeInteger(number) || number > row.quantity) {
          input.value = String(picked.sideboard?.[row.name] || 0);
          error.textContent = `Choose a whole number from 0 to ${row.quantity} for ${row.name}.`;
          return;
        }
        const next = { ...(picked.sideboard || {}) };
        if (number) next[row.name] = number; else delete next[row.name];
        picked.sideboard = next;
        view.sideboardChoosing ||= new Set(); view.sideboardChoosing.add(picked.id);
        packChanged(view);
      });
      fields.append(el("label", { class: "field" }, el("span", { text: `${row.name} (of ${row.quantity})` }), input));
    }
    node.append(fields, error);
  }
  const count = chosen ? Object.values(chosen).reduce((sum, qty) => sum + qty, 0) : intended;
  node.append(el("p", { class: "sub", text: `Full main deck + ${count} of ${intended} intended sideboard cards. `
    + "Packed sideboard cards omitted here will be put back. The intended list stays saved." }));
  return node;
}

function packScopeWords(deck) {
  return deck.build_scope?.label || "All listed sections, including any sideboard";
}

/** Unassembled is separate from unavailable: an omitted owned card still belongs to the intention. */
function remainingIntentPart(rows, title = "Still intended for this deck", folded = true) {
  if (!rows?.length) return null;
  const count = rows.reduce((sum, row) => sum + row.remaining, 0);
  const lines = rows.map(row => {
    const notes = [`${row.assembled} assembled`, `${row.remaining} not assembled`];
    if (row.missing) notes.push(`${row.missing} to get`);
    if (row.on_the_way) notes.push(`${row.on_the_way} on the way`);
    if (row.missing === null || row.on_the_way === null) notes.push("availability needs checking");
    return el("li", {}, `${row.intended} x ${row.name} (${row.section}): ${notes.join("; ")}`);
  });
  return el(folded ? "details" : "section", { class: "pack-remaining-intent pack-fold" },
    el(folded ? "summary" : "h3", { text: `${title} (${plural(count, "card")})` }),
    el("p", { class: "sub", text: "These cards remain in this deck's intended list." }),
    el("ul", {}, lines));
}

function assembledStateWords(info) {
  return `Physically assembled: ${plural(info.main_count, "main-deck card")}`
    + (info.sideboard_intended || info.sideboard_count
      ? ` + ${info.sideboard_count} of ${info.sideboard_intended} intended sideboard cards` : "");
}

function deckAssemblySection(data) {
  if (!("owned" in data)) return null;
  const info = data.assembled || data.summary.assembled;
  if (!info) return null;
  return el("section", { class: "deck-section deck-assembly", "aria-label": "Physically assembled cards" },
    el("h2", { text: "Physically assembled" }), el("p", { text: assembledStateWords(info) + "." }),
    info.changed ? el("p", { class: "box box-warn", text: "The physical assembly differs from the intended list. Review the packing plan before changing the physical deck." }) : null,
    remainingIntentPart(info.remaining),
    el("a", { class: "btn", href: `#/assembly?deck=${encodeURIComponent(data.summary.id)}&version=${info.intended_version || info.version}`,
      text: "Review the packing plan" }));
}
