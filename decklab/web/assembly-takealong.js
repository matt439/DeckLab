/* One optional take-along checklist for already-built decks. Shared packing ticks store its
 * checks; neither checking it nor printing it changes a physical build, kit or inventory. */
"use strict";

function assemblyTakeAlongTick(row) {
  const node = assemblyTick(row.title, 1, row.context, row.task);
  node.querySelector("input").setAttribute("class", "pack-tick-optional pack-takealong-tick");
  node.append(...row.lines.map(text => el("p", { class: "sub pack-takealong-detail", text })));
  return node;
}

function assemblyTakeAlongHere(view, data, model, button) {
  const owner = view.takeAlong;
  try {
  return assemblyActive(view) && view.hash === location.hash && seesHomeInventory(state.may)
    && view.data === data && data.take_along === model && model.available === true
    && owner?.model === model && owner.button === button && owner.data === data && owner.profile === state.profile
    && owner.main === document.getElementById("main") && owner.main?.isConnected && owner.main.contains(view.root)
    && view.root.parentNode === owner.rootParent && owner.section.parentNode === view.results
    && JSON.stringify(model) === owner.facts && JSON.stringify(view.selected.map(packSelectedChoice)) === owner.recipe
    && button.isConnected && button.parentNode === owner.actions && !button.hidden && !owner.actions.hidden
    && owner.actions.parentNode === owner.section && !owner.section.hidden && !view.results.hidden
    && !button.disabled && !view.previewing && !view.saving && !view.reviewing
    && !document.querySelector("dialog[open]");
  } catch (_) { return false; }
}

function printAssemblyTakeAlong(view, data, model, button) {
  if (!assemblyTakeAlongHere(view, data, model, button)) return;
  const rows = [...model.decks, ...model.counters];
  const marked = row => (view.ticks || []).some(tick => tick.optional && tick.done
    && tick.node.getAttribute("data-pack-tick") === row.task
    && tick.node.getAttribute("data-pack-context") === JSON.stringify(row.context));
  const list = items => el("ul", {}, items.map(row => el("li", {},
    el("b", { text: `${marked(row) ? "[x]" : "[ ]"} ${row.title}` }),
    ...row.lines.map(text => el("p", { text })))));
  const sheet = el("article", { class: "print-sheet pack-takealong-print" },
    el("h1", { text: "Take-along list" }),
    el("p", { text: "Optional packing reminders for the selected built decks." }),
    el("h2", { text: "Decks" }), list(model.decks),
    model.counters.length ? [el("h2", { text: "Counters and dice" }),
      model.counter_note ? el("p", { text: model.counter_note }) : null, list(model.counters)] : null,
    model.counter_error ? el("p", { text: model.counter_error }) : null,
    model.playmats.length ? [el("h2", { text: "Playmats" }),
      el("p", { text: model.playmats.join("; ") })] : null,
    model.playmats_error ? el("p", { text: model.playmats_error }) : null);
  // Building text nodes cannot authorize a departed page's retained control.
  if (!rows.length || !assemblyTakeAlongHere(view, data, model, button)) return;
  document.querySelector(".print-sheet")?.remove();
  document.body.append(sheet);
  window.addEventListener("afterprint", () => sheet.remove(), { once: true });
  window.print();
}

function assemblyTakeAlong(view, data) {
  const model = data.take_along;
  view.takeAlong = null;
  if (!model) return null;
  if (!model.available) return el("p", { class: "sub pack-takealong-unavailable", text: model.reason });
  const button = el("button", { type: "button", class: "btn", text: "Print take-along list" });
  const actions = el("div", { class: "actions" }, button);
  const section = el("section", { class: "panel pack-extra pack-takealong" },
    el("h2", { text: "Take-along list" }),
    el("p", { class: "sub", text: "For these built decks. These optional checks are shared and don't change the decks or their cards." }),
    actions,
    el("h3", { text: "Decks" }), el("ul", { class: "pack-list" }, model.decks.map(assemblyTakeAlongTick)),
    model.counters.length ? [el("h3", { text: "Counters and dice" }),
      model.counter_note ? el("p", { class: "sub", text: model.counter_note }) : null,
      el("ul", { class: "pack-list" }, model.counters.map(assemblyTakeAlongTick))] : null,
    model.counter_error ? el("p", { class: "sub assembly-pending", text: model.counter_error }) : null,
    model.playmats.length ? el("p", { class: "sub", text: `Playmats to remember: ${model.playmats.join("; ")}` }) : null,
    model.playmats_error ? el("p", { class: "sub assembly-pending", text: model.playmats_error }) : null);
  view.takeAlong = { model, data, button, actions, section, profile: state.profile,
    main: document.getElementById("main"), rootParent: view.root.parentNode, facts: JSON.stringify(model),
    recipe: JSON.stringify(view.selected.map(packSelectedChoice)) };
  button.addEventListener("click", () => printAssemblyTakeAlong(view, data, model, button));
  return section;
}
