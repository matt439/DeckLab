/* Competition uses the current confirmed plan; optional server-verified priorities only change its recipe. */
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
  view.playableOverlap = { data, rows, names: new Map(rows.map(row => [row.name, row])), controls: new Set() };
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

/** Only the server can identify movable, marker-free recipients. Check its mapping against this plan. */
function packOverlapPreference(view, row) {
  const source = view.data.rows.find(item => item.name === row.name), ids = source?.preference_options;
  const eligible = row.participants.filter(p => p.need > p.keep);
  if (!Array.isArray(ids) || ids.length < 2 || new Set(ids).size !== ids.length || ids.length !== eligible.length
      || !ids.every((id, index) => id === eligible[index].id
        && view.selected.some(choice => choice.id === id && choice.version === eligible[index].version))
      || !row.participants.some(p => p.storage + p.transferred > 0)
      || !(source.preferred === null || ids.includes(source.preferred))) return null;
  const owners = view.selected.filter(choice => Array.isArray(choice.prefer) && choice.prefer.includes(row.name));
  if (owners.length > 1 || (owners[0]?.id || null) !== source.preferred) return null;
  return { options: eligible, preferred: source.preferred };
}

function packPreferenceCanChange(view, data, overlap, recipe, control) {
  return packOverlapHere(view) && view.hash === location.hash && view.data === data && view.playableOverlap === overlap
    && control.isConnected && view.results.contains(control) && !control.disabled
    && !view.previewing && !view.reviewing && !view.saving && !document.querySelector("dialog[open]")
    && recipe === JSON.stringify(view.selected.map(packSelectedChoice));
}

/** Capture ownership before the old results detach, including the native select still awaiting its preview. */
function packPreferenceBeforeRender(view) {
  const node = document.activeElement;
  view.preferenceFocus = packOverlapHere(view) && view.hash === location.hash && view.playableOverlap?.controls?.has(node)
    && node.isConnected && view.results.contains(node) && !view.previewing && !view.saving && !view.reviewing
    && !document.querySelector("dialog[open]")
    ? { node, name: node.getAttribute("data-pack-preference") } : null;
  view.preferenceFocusRepair = null;
}

function packPreferenceAfterRender(view, notice, heading) {
  const focus = view.preferenceFocus;
  view.preferenceFocus = null;
  if (!focus) return;
  const data = view.data, overlap = view.playableOverlap, seq = view.seq;
  const recipe = JSON.stringify(view.selected.map(packSelectedChoice));
  const target = (focus.name && [...(notice?.querySelectorAll("[data-pack-preference]") || [])]
    .find(node => node.getAttribute("data-pack-preference") === focus.name))
    || notice?.querySelector("[data-pack-priority-reset]") || heading
    || (view.chooserHeading?.isConnected ? view.chooserHeading : view.chooserLaunch);
  view.preferenceFocusRepair = focus;
  Promise.resolve().then(() => {
    if (view.preferenceFocusRepair !== focus) return;
    view.preferenceFocusRepair = null;
    if (!packOverlapHere(view) || view.hash !== location.hash || view.data !== data || view.playableOverlap !== overlap
        || seq !== view.seq || recipe !== JSON.stringify(view.selected.map(packSelectedChoice))
        || view.previewing || view.saving || view.reviewing || document.querySelector("dialog[open]")
        || focus.node.isConnected || !target?.isConnected || !view.root.contains(target)
        || ![document.body, focus.node].includes(document.activeElement)) return;
    target.focus();
  });
}

/** Priorities never reassign kept cards or arrivals; the next ordinary preview supplies all instructions. */
function packPreferenceSelect(view, row) {
  const preference = packOverlapPreference(view, row);
  if (!preference) return null;
  const data = view.data, overlap = view.playableOverlap, recipe = JSON.stringify(view.selected.map(packSelectedChoice));
  const accepted = preference.preferred || "";
  const select = el("select", { "aria-label": `Give free copies of ${row.name} first to`, "data-pack-preference": row.name },
    el("option", { value: "", text: "Default selection order", selected: !accepted }),
    preference.options.map(p => el("option", { value: p.id, text: `${p.title} (${listName(p.version)})`, selected: p.id === accepted })));
  select.value = accepted;
  overlap.controls.add(select);
  const restore = () => { select.value = view.selected.find(choice => Array.isArray(choice.prefer)
    && choice.prefer.includes(row.name) && preference.options.some(p => p.id === choice.id))?.id || ""; };
  select.addEventListener("change", () => {
    if (!packPreferenceCanChange(view, data, overlap, recipe, select)) { restore(); return; }
    const recipient = select.value;
    if (recipient !== "" && !preference.options.some(p => p.id === recipient)) { restore(); return; }
    if (recipient === accepted) return;
    for (const choice of view.selected) {
      const names = (choice.prefer || []).filter(name => name !== row.name);
      if (choice.id === recipient) names.push(row.name);
      if (names.length) choice.prefer = names; else delete choice.prefer;
    }
    packChanged(view);
  });
  return el("label", { class: "field pack-overlap-preference" },
    el("span", { text: `Give free copies of ${row.name} first to` }), select);
}

function packPreferenceReset(view) {
  if (!view.selected.some(choice => choice.prefer?.length)) return null;
  const data = view.data, overlap = view.playableOverlap, recipe = JSON.stringify(view.selected.map(packSelectedChoice));
  const reset = el("button", { type: "button", class: "btn btn-quiet", "data-pack-priority-reset": "",
    text: "Reset card priorities", onclick: () => {
    if (!packPreferenceCanChange(view, data, overlap, recipe, reset)) return;
    for (const choice of view.selected) delete choice.prefer;
    packChanged(view);
  } });
  overlap.controls.add(reset);
  return reset;
}

function packOverlapNotice(view) {
  if (!packOverlapHere(view)) return null;
  const reset = packPreferenceReset(view);
  if (!view.playableOverlap.rows.length && !reset) { packPreferenceAfterRender(view, null, null); return null; }
  const number = n => el("span", { class: "pack-overlap-number", text: String(n) });
  const rows = view.playableOverlap.rows.map(row => {
    const participants = row.participants.map(p => el("li", {},
      el("strong", { text: `${p.title} (${listName(p.version)})` }),
      el("span", { class: "pack-overlap-facts" }, number(p.need), " needed; ", number(p.assigned), " assigned; ",
        number(p.waiting), " waiting; ", number(p.missing), " missing.")));
    return el("tr", {}, el("th", { scope: "row", text: row.name }),
      el("td", {}, el("ul", { class: "pack-overlap-decks" }, participants), packPreferenceSelect(view, row)));
  });
  const heading = el("h2", { class: "box-head", tabindex: "-1", text: rows.length ? "Cards needed by more than one deck" : "Card priorities" });
  const notice = el("section", { class: "box box-warn pack-overlap", role: "note",
    "aria-label": rows.length ? "Cards needed by more than one deck" : "Card priorities" },
    heading,
    el("p", { text: rows.length
      ? "The current plan assigns copies to one selected deck while another is waiting or still short. Checking tasks does not change these assignments."
      : "Card priorities are kept in this recipe. Reset them to retry in selection order." }),
    reset,
    rows.length ? el("table", { class: "pack-overlap-table" },
      el("caption", { class: "sr-only", text: "Current selected decks and lists. All quantities are card copies." }),
      el("thead", {}, el("tr", {}, el("th", { scope: "col", text: "Card" }), el("th", { scope: "col", text: "Current plan (copies)" }))),
      el("tbody", {}, rows)) : null);
  packPreferenceAfterRender(view, notice, heading);
  return notice;
}
