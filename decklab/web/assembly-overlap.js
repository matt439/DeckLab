/* Informational competition uses the current confirmed card-name plan, never another allocation. */
"use strict";

function packPlayableOverlap(data) {
  if (data?.counts_confirmed !== true || !Array.isArray(data.decks) || !Array.isArray(data.rows)) return [];
  const whole = n => Number.isSafeInteger(n) && n >= 0;
  const named = name => typeof name === "string" && name.length > 0 && name.trim() === name;
  const transferCount = transfers => Array.isArray(transfers) && transfers.every(t => t && whole(t.quantity))
    ? transfers.reduce((sum, t) => sum + t.quantity, 0) : NaN;
  const ids = new Set(), excluded = new Set(), grouped = new Map(), invalid = new Set(), aggregates = new Map();
  for (const deck of data.decks) {
    if (!deck || !named(deck.id) || !named(deck.title) || !["target", "owned"].includes(deck.version)
        || ids.has(deck.id) || !Array.isArray(deck.steps) || !Array.isArray(deck.standins?.rows)) return [];
    ids.add(deck.id);
    for (const row of deck.standins.rows) {
      if (!row || !named(row.for) || !(row.using === null || named(row.using)) || !whole(row.qty) || !row.qty) return [];
      excluded.add(row.for);
      if (row.using !== null) excluded.add(row.using);
    }
    const seen = new Set();
    for (const step of deck.steps) {
      if (!step || !named(step.name)) return [];
      const name = step.name, transferred = transferCount(step.transfers);
      const assigned = step.keep + step.storage + transferred;
      if (seen.has(name) || step.resolved !== true || ![step.need, step.keep, step.storage, step.waiting, step.missing, transferred, assigned].every(whole)
          || step.need !== assigned + step.waiting + step.missing) { invalid.add(name); continue; }
      seen.add(name);
      if (!step.need) continue;
      if (!grouped.has(name)) grouped.set(name, []);
      grouped.get(name).push({ id: deck.id, title: deck.title, version: deck.version, need: step.need,
        keep: step.keep, storage: step.storage, transferred, assigned, waiting: step.waiting, missing: step.missing });
    }
  }
  for (const row of data.rows) {
    if (!row || !named(row.name)) return [];
    if (aggregates.has(row.name)) invalid.add(row.name);
    aggregates.set(row.name, row);
  }
  const result = [];
  for (const [name, participants] of grouped) {
    if (excluded.has(name) || invalid.has(name) || participants.length < 2) continue;
    const row = aggregates.get(name), sum = key => participants.reduce((total, p) => total + p[key], 0);
    if (!row || ![row.need, row.kept, row.from_storage, row.waiting, row.missing, transferCount(row.transfers)].every(whole)
        || row.need !== sum("need") || row.kept !== sum("keep") || row.from_storage !== sum("storage")
        || row.waiting !== sum("waiting") || row.missing !== sum("missing") || transferCount(row.transfers) !== sum("transferred")) continue;
    if (!participants.some(p => p.assigned > 0 && participants.some(other => other.id !== p.id && other.waiting + other.missing > 0))) continue;
    result.push({ name, participants, waiting: sum("waiting"), missing: sum("missing") });
  }
  return result;
}

function packOverlapStart(view, data) {
  const rows = packSwitcherHere(view) ? packPlayableOverlap(data) : [];
  view.playableOverlap = { data, rows, names: new Map(rows.map(row => [row.name, row])) };
}

function packOverlapHere(view) {
  return packSwitcherHere(view) && view.playableOverlap?.data === view.data;
}

function packOverlapPill(view, name, participant) {
  if (!participant || !packOverlapHere(view)) return null;
  const row = view.playableOverlap.names.get(name);
  if (!row?.participants.some(p => p.id === participant.id && p.version === participant.version)) return null;
  const others = row.participants.filter(p => p.id !== participant.id);
  const full = "Also needed by " + others.map(p => `${p.title} (${listName(p.version)})`).join(", ");
  return el("span", { class: "status status-warn pack-overlap-pill", title: full },
    el("span", { class: "pack-overlap-short", "aria-hidden": "true", text: "Also needed" }),
    el("span", { class: "pack-overlap-full", text: full }));
}

function packOverlapNotice(view) {
  if (!packOverlapHere(view) || !view.playableOverlap.rows.length) return null;
  const number = n => el("span", { class: "pack-overlap-number", text: String(n) });
  const rows = view.playableOverlap.rows.map(row => {
    const participants = row.participants.map(p => el("li", {},
      el("strong", { text: `${p.title} (${listName(p.version)})` }),
      el("span", { class: "pack-overlap-facts" }, number(p.need), " needed; ", number(p.assigned), " assigned; ",
        number(p.waiting), " waiting; ", number(p.missing), " missing.")));
    return el("tr", {}, el("th", { scope: "row", text: row.name }),
      el("td", {}, el("ul", { class: "pack-overlap-decks" }, participants)));
  });
  return el("section", { class: "box box-warn pack-overlap", role: "note", "aria-label": "Cards needed by more than one deck" },
    el("h2", { class: "box-head", text: "Cards needed by more than one deck" }),
    el("p", { text: "The current plan assigns copies to one selected deck while another is waiting or still short. Checking tasks does not change these assignments." }),
    el("table", { class: "pack-overlap-table" },
      el("caption", { class: "sr-only", text: "Current selected decks and lists. All quantities are card copies." }),
      el("thead", {}, el("tr", {}, el("th", { scope: "col", text: "Card" }), el("th", { scope: "col", text: "Current plan (copies)" }))),
      el("tbody", {}, rows)));
}
