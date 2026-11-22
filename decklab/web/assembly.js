/* The packing plan (UI-REVIEW.md WP10, INV-4, INV-5): choose the decks that need to exist together from a
checklist, and the plan (POST /api/assembly/preview, which writes nothing) is worked out at once. Each deck's
plan is grouped into steps: sleeves; pull from storage; move from other decks; basics; tokens; put back; pack;
with what's still waiting folded at the end. Cards are picture tiles, each with a tick, and every picture opens
the card viewer over the whole plan ("packing"). A sticky bar says how far the packing has got ("Pulled 12 of
31 cards"); the ticks are shared through the server (assembly-progress.js) and never reserve or change
inventory. Each deck's sleeves and deck box (its "kit") use accessories.js's accessoryThumb() and, where none
are recorded, its kitPicker(); decks chosen together that share one design of sleeves get a note (sleeve_notes),
never a block. Each deck's tokens come from the server's deck_tokens (lib/tokens) and are always optional
(assembly-tokens.js). Once the card tasks are checked, Mark as built saves the selected lists together; ticks alone never change the deck's status. */
"use strict";

const PACK_MAX = 12;                    // decks in one plan (lib/api/assembly.py MAX_DECKS)
const PACK_DELAY = 250;                 // ms after a change before the plan is worked out again
const PACK_GROUPS = [["built", "Built"], ["building", "Being built"], ["idea", "Ideas"], ["product", "Products"]];
let packProductReviewReturn = null;        // one-use, in-memory intent for one person and assembly address

function showAssembly(params, token) {
  const hash = location.hash, profile = state.profile?.id;
  const check = takeRequestedBoxCheck(hash);
  const returning = packProductReviewReturn;
  if (returning && (returning.hash !== hash || returning.profile !== profile)) packProductReviewReturn = null;
  const query = new URLSearchParams();
  const id = params.get("deck") || params.get("id");
  if (id) { query.set("deck", id); query.set("version", params.get("version") || "target"); }
  const selectedIds = !id && params.get("decks") ? params.get("decks").split(",", PACK_MAX) : [];
  return load(`/api/assembly?${query}`, token, data => {
    if (token !== routeToken || profile !== state.profile?.id || hash !== location.hash) return;
    const restore = returning && packProductReviewReturn === returning;
    if (restore) packProductReviewReturn = null;
    const choices = data.choices.filter(choice => !choice.error && choice.versions?.includes("target"));
    const recipe = [...new Set(selectedIds)].filter(id => choices.some(choice => choice.id === id))
      .map(id => ({ id, version: "target" }));
    return drawAssembly(data, token, restore ? returning.recipe : recipe.length ? recipe : null, Boolean(restore), check);
  });
}

/** The group a deck choice is listed under: its status, or "product" for a product's decks. */
function packGroupOf(choice) {
  if (String(choice.id).startsWith("product/")) return "product";
  return ["built", "building"].includes(choice.status) ? choice.status : "idea";
}

function drawAssembly(data, token, initialRecipe = null, returningFromProduct = Boolean(initialRecipe), boxCheckStart = null) {
  const sortKey = `packing-order.${state.profile?.id || "guest"}`;
  const view = { token, hash: location.hash, profile: state.profile?.id, choices: data.choices.filter(item => !item.error && item.versions?.length),
    selected: (initialRecipe || data.selections || data.decks).map(packSelectedChoice), seq: 0, timer: null,
    sortKey, order: local.get(sortKey) === "storage" ? "storage" : "name", storageRule: packStorageRule(null), boxCheckStart };
  view.root = el("div", { class: "pack-page" });
  view.results = el("div", { class: "pack-results", "aria-live": "polite" });
  view.message = el("p", { class: "pack-message", role: "status" });
  view.messageSlot = el("div", { class: "pack-message-slot" }, view.message);
  view.progressNote = el("div", { class: "pack-sync", role: "status" });
  view.picks = el("div", { class: "pack-picks" });
  view.sortControl = packOrderControls(view);
  const from = parseHash().params.get("deck");
  const fromDeck = from && (data.choices.find((item) => item.id === from) || { id: from, title: "The deck" });
  view.chooserCount = el("span", { class: "pack-choose-count" });
  view.chooserHeading = el("h2", { class: "pack-choose-head", tabindex: "-1" },
    el("span", { class: "pack-choose-title", text: "Decks" }), view.chooserCount);
  view.chooser = el("section", { class: "panel pack-choose", "aria-label": "Deck choices" }, view.chooserHeading,
    el("div", { class: "actions pack-presets" },
      el("button", { type: "button", class: "btn", text: "Built and being built", "data-pack-id": "", "data-pack-control": "preset", onclick: e => {
        if (!packChooserCanChange(view, e.currentTarget)) return;
        view.sideboardChoosing?.clear();
        view.selected = view.choices.filter(c => ["built", "building"].includes(packGroupOf(c))).slice(0, PACK_MAX)
          .map(c => ({ id: c.id, version: "target" }));
        packChanged(view);
      } }),
      el("button", { type: "button", class: "btn btn-quiet", text: "Clear", "data-pack-id": "", "data-pack-control": "clear", onclick: e => {
        if (!packChooserCanChange(view, e.currentTarget)) return;
        view.selected = []; view.sideboardChoosing?.clear(); packChanged(view);
      } })),
    view.picks);
  // Nothing to choose: the presets above hide with the list (assembly.css), and the library is where decks are made.
  view.chooserEmpty = emptyBox("No decks to choose yet.", el("a", { class: "btn", href: "#/library", text: "Go to the library" }));
  view.chooserEmpty.classList.add("pack-chooser-empty");
  view.chooser.append(view.chooserEmpty);
  view.chooserLaunch = el("button", { type: "button", class: "btn pack-chooser-launcher", text: "Decks",
    "aria-haspopup": "dialog", "aria-expanded": "false", onclick: () => packRevealChooser(view) });
  view.chooserRail = el("div", { class: "pack-chooser-rail" });
  view.chooserSlot = el("div", { class: "pack-chooser-slot" }, view.chooserRail);
  view.planMain = el("div", { class: "pack-main" }, view.chooserLaunch, view.messageSlot, view.progressNote, view.sortControl, view.results);
  add(view.root, [
    pageHead({ crumb: fromDeck ? [deckHref(fromDeck.id, parseHash().params.get("version")), fromDeck.title || "The deck"] : null,
      title: fromDeck ? (data.decks[0]?.completion?.status === "built" ? "Review build" : "Build deck") : routeH1("assembly"),
      description: fromDeck ? null : "Choose decks to pack together. Each physical copy is counted once." }),
    el("div", { class: "pack-layout" }, view.chooserSlot, view.planMain)]);
  $("#main").append(view.root);
  view.run = () => packRun(view);
  packInitChooser(view);
  packInitSwitcher(view);
  packInitSteps(view);
  drawPackPicks(view);
  if (initialRecipe) {
    // Fresh choices are useful immediately; allocations are never replayed from the departed plan or GET default.
    view.productReturnRefresh = returningFromProduct;
    view.sortControl.hidden = true;
    packRun(view);
  } else renderAssemblyPlan(view, data);
  return view;
}

function assemblyActive(view) {
  return view.token === routeToken && view.profile === state.profile?.id && view.root.isConnected;
}

/** The checklist of decks, grouped by status, each with its list (planned or play-now) once it's chosen. */
function drawPackPicks(view) {
  const presentation = packChooserBeforeDraw(view);
  clear(view.picks);
  const full = view.selected.length >= PACK_MAX;
  const selected = new Set(view.selected.map(item => item.id));
  const usual = new Set(view.choices.filter(choice => selected.has(choice.id))
    .flatMap(choice => choice.usual_opponents || []).filter(id => !selected.has(id)));
  for (const [key, words] of [["usual", "Usual opponents"], ...PACK_GROUPS]) {
    const choices = view.choices.filter(c => key === "usual" ? usual.has(c.id) : !usual.has(c.id) && packGroupOf(c) === key);
    if (!choices.length) continue;
    const list = el("ul", { class: "pack-picklist" }, choices.map((choice) => {
      const picked = view.selected.find(s => s.id === choice.id);
      const box = el("input", { type: "checkbox", checked: Boolean(picked), disabled: !picked && full,
        "data-pack-id": choice.id, "data-pack-control": "choose",
        onchange: () => {
          const accepted = view.selected.some(s => s.id === choice.id);
          if (!packChooserCanChange(view, box) || !view.choices.includes(choice)
              || (box.checked && !accepted && view.selected.length >= PACK_MAX)) { box.checked = accepted; return; }
          if (box.checked && !accepted) view.selected.push({ id: choice.id, version: "target" });
          else if (box.checked) return;
          else {
            view.selected = view.selected.filter(s => s.id !== choice.id);
            view.sideboardChoosing?.delete(choice.id);
          }
          packChanged(view);
        } });
      const versions = picked && (choice.versions || []).length > 1
        ? el("div", { class: "segmented pack-version", role: "group", "aria-label": `${choice.title}: which list` },
          choice.versions.map(v => el("button", { type: "button", "aria-pressed": String(picked.version === v), text: listName(v),
            "data-pack-id": choice.id, "data-pack-control": `version:${v}`,
            onclick: event => packChooseVersion(view, picked, v, event.currentTarget) }))) : null;
      return el("li", {}, el("label", { class: "choice" }, box, el("span", { text: choice.title })), versions,
        packSideboardChoice(view, choice, picked));
    }));
    // Ideas and products are folded until one of them is chosen.
    const shut = (key === "idea" || key === "product") && !choices.some(c => view.selected.some(s => s.id === c.id));
    view.picks.append(shut ? el("details", { class: "pack-group", "data-pack-group": key }, el("summary", { text: `${words} (${choices.length})` }), list)
      : el("div", { class: "pack-group", "data-pack-group": key }, el("h3", { text: words }), list));
  }
  if (full) view.picks.append(el("p", { class: "sub", text: `A plan holds up to ${PACK_MAX} decks.` }));
  packChooserAfterDraw(view, presentation);
}

/** A choice changed: redraw the checklist and work the plan out again shortly after. */
function packChanged(view) {
  if (assemblyActive(view)) packProductReviewReturn = null;
  view.boxCheckStart = null;
  closeAssemblySheets(false);
  ++view.seq;
  view.builtMessage = null;
  view.finishError = null;
  view.previewing = true;
  packProgress(view);
  drawPackPicks(view);
  clearTimeout(view.timer);
  view.timer = setTimeout(view.run, PACK_DELAY);
}

async function packRun(view) {
  if (!assemblyActive(view)) return;
  const seq = ++view.seq;
  view.previewing = true;
  packProgress(view);
  // Waiting words with a small spinner; any later textContent write drops the spinner with them.
  clear(view.message);
  if (view.selected.length) view.message.append(el("span", { class: "spinner spinner-small", "aria-hidden": "true" }), "Working out the plan…");
  try {
    const result = await apiWrite("/api/assembly/preview", { decks: view.selected.map(item => ({ ...item })) });
    if (!assemblyActive(view) || seq !== view.seq) return;
    view.previewing = false;
    view.productReturnRefresh = false;
    view.builtMessage = null;
    view.finishError = null;
    view.message.textContent = "";
    // A separately reviewed take-apart save (including a lost response) may have changed these statuses.
    let statusesChanged = false;
    view.choices = view.choices.map(choice => {
      const status = result.decks?.find(deck => deck.id === choice.id)?.completion?.status;
      if (!["idea", "building", "built"].includes(status) || status === choice.status) return choice;
      statusesChanged = true;
      return { ...choice, status };
    });
    if (result.selections) {
      view.selected = result.selections.map(packSelectedChoice);
      drawPackPicks(view);
    } else if (statusesChanged) drawPackPicks(view);
    renderAssemblyPlan(view, result);
  } catch (problem) {
    if (assemblyActive(view) && seq === view.seq) {
      view.previewing = false;
      view.message.textContent = problem.message;
      packClearBar(view);
      packPreferenceBeforeRender(view);
      clear(view.results);
      view.sortControl.hidden = true;
      view.data = null;
      packStepsStart(view, null);
      packOverlapStart(view, null);
      add(view.results, [packOverlapNotice(view)]);
      view.finish = null;
      view.bar = null;
      wirePackTicks(view);
      // Running the same choices again is the retry; after a product review it's the stale note's Refresh plan.
      // The reason stays on the status line (it follows the chooser into its sheet), so this note isn't announced again.
      const again = (button) => {
        if (!assemblyActive(view) || view.hash !== location.hash || !button.isConnected || !view.results.contains(button)
            || view.seq !== seq || view.data !== null || view.previewing || view.saving || view.reviewing) return;
        button.disabled = true; view.run();
      };
      if (!view.productReturnRefresh) {
        const retry = problem.status === 400 ? null
          : el("button", { type: "button", class: "btn", text: "Try again", onclick: () => again(retry) });
        view.results.append(el("div", { class: "note note-crit pack-failed" },
          el("p", { text: "The plan couldn't be worked out. Your decks are still chosen." }), retry));
      } else {
        const retry = el("button", { type: "button", class: "btn", text: "Refresh plan", onclick: () => {
          if (view.productReturnRefresh) again(retry);
        } });
        view.results.append(el("div", { class: "note note-stale" },
          el("p", { text: "Refresh the plan to see its card instructions. Your decks and sideboard choices are kept." }), retry));
      }
    }
  }
}

/** A supplied verified relationship, never a product guessed from a holder's id or name. */
function packIntactProduct(holder) {
  const product = holder?.intact_product;
  if (!product || typeof product !== "object" || Array.isArray(product)
      || !["id", "title", "deck_id"].every(key => typeof product[key] === "string" && product[key].trim()
        && product[key].length <= 1000 && !/[\u0000-\u001f\u007f]/.test(product[key]))
      || !/^product\/[^?#\s]+$/.test(product.deck_id)) return null;
  return product;
}

function packProductReviewHere(view, data, recipe, link) {
  return assemblyActive(view) && view.hash === location.hash && seesHomeInventory(state.may)
    && view.data === data && link.isConnected && view.results.contains(link)
    && recipe === JSON.stringify(view.selected.map(packSelectedChoice));
}

/** Review the existing storage choice separately; one settled plan recipe survives Browser Back. */
function packProductReviewLink(view, data, product) {
  const href = `${deckHref(product.deck_id)}&tab=overview`, recipe = JSON.stringify(view.selected.map(packSelectedChoice));
  const link = el("a", { class: "btn", href, text: `Review ${product.title}`, onclick: event => {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button > 0) return;
    event.preventDefault();
    if (!packProductReviewHere(view, data, recipe, link)) return;
    if (view.previewing || view.reviewing || view.saving || document.querySelector("dialog[open]")) {
      packProductReviewReturn = null;
      view.message.textContent = "Finish the current plan change before reviewing this product.";
      return;
    }
    const progress = view.progress;
    if (!progress?.loaded || progress.busy || progress.pending.size || progress.error) {
      packProductReviewReturn = null;
      view.message.textContent = progress?.error || progress?.pending.size
        ? "Save the shared packing checks before reviewing this product."
        : "Wait for the shared packing checks to finish loading, then review this product.";
      return;
    }
    packProductReviewReturn = { profile: view.profile, hash: view.hash,
      recipe: view.selected.map(packSelectedChoice) };
    location.hash = href;
  } });
  return link;
}

function packIntactProductsPart(view, data) {
  const groups = new Map();
  for (const row of data.rows || []) {
    if (!(Number.isSafeInteger(row.missing) && row.missing > 0 || Number.isSafeInteger(row.waiting) && row.waiting > 0)) continue;
    for (const holder of row.held_elsewhere || []) {
      const product = packIntactProduct(holder);
      if (!product || !Number.isSafeInteger(holder.quantity) || holder.quantity <= 0) continue;
      const key = product.id; // One physical product may have several verified generated deck routes.
      if (!groups.has(key)) groups.set(key, { product, cards: new Map() });
      const cards = groups.get(key).cards;
      cards.set(row.name, (cards.get(row.name) || 0) + holder.quantity);
    }
  }
  if (!groups.size) return null;
  return el("section", { class: "panel pack-extra pack-intact-products", "aria-label": "Cards held in intact products" },
    el("h2", { text: "Cards held in intact products" }),
    el("p", { text: "These products keep their cards together. Review their storage choice before using any copies here. "
      + "Use your browser's Back action to return to the same selected decks and refresh this plan." }),
    [...groups.values()].map(({ product, cards }) => el("div", {}, el("h3", { text: product.title }),
      el("ul", {}, [...cards].map(([name, quantity]) => el("li", { text: `${quantity} x ${name} held in this product` }))),
      packProductReviewLink(view, data, product))));
}

/** A tick in a list; physical context distinguishes kit variants with the same label. */
function assemblyTick(text, count = 1, context = null, key = text) {
  return el("li", {}, el("label", { class: "pack-row" },
    el("input", { type: "checkbox", "data-pack-tick": key, "data-pack-count": count,
      "data-pack-context": context ? JSON.stringify(context) : "" }), el("span", { text })));
}

// Tiles are at least 220 px from a tablet up (assembly.css), so a retina iPad takes the 488 px picture, not the small one.
const PACK_TILE_SIZES = "(max-width: 599px) 50vw, 300px";

/** A card to pull as a picture tile with a tick on its corner; id is its key for the saved ticks. */
function packTile(view, name, { qty, meta, caption, id, label = name, finishes = [], overlap = null, printing = null }) {
  const card = (view.cards || {})[name] || null;
  // These are the selected list's finishes; allocation still counts interchangeable copies by name.
  const special = finishes.some(item => ["foil", "etched"].includes(item.finish));
  const finish = special && finishes.length === 1 ? finishes[0].finish : null;
  const finishWords = special ? finishes.map(item =>
    `${finishes.length > 1 ? `${item.quantity} ` : ""}${item.finish || "unspecified"}`).join(" · ") : "";
  const chips = special && !finish
    ? [el("span", { class: "chip chip-plain chip-foil", text: `List: ${finishWords}` })] : [];
  const description = finishWords ? `${caption}. Deck list: ${finishWords}` : caption;
  const tick = el("button", { type: "button", class: "tile-tick pack-tick", "aria-pressed": "false",
    "aria-label": `${qty > 1 ? `${qty} × ` : ""}${label}: done`, "data-pack-tick": id, "data-pack-count": qty,
    "data-pack-context": JSON.stringify(finishes.map(f => [f.finish, f.quantity]).sort()) });
  const tile = cardTile(card, { qty, name: frontName(label), meta, finish, chips, state: tick, sizes: PACK_TILE_SIZES,
    onclick: card ? event => packOpenCard(view, event.currentTarget) : null,
    viewerGroup: "packing", caption: description, label: finishWords ? `${label}. ${description}` : card ? null : label });
  packRegisterCard(view, tile, card, description);
  const pill = packOverlapPill(view, name, overlap);
  if (pill) tile.append(pill);
  if (printing) tile.append(printing);
  return tile;
}

/** Home's storage order (E8-S25 slice 5): the plan's "storage_order", its default container's rule.
 * An answer without the field (an older server) is today's colour-and-type order; null (no default
 * container) and an unknown rule are "none". */
function packStorageRule(data) {
  if (!data || !Object.hasOwn(data, "storage_order")) return { rule: "colour-type", container: null, printings: {} };
  const order = data.storage_order;
  if (!order || typeof order !== "object") return { rule: "none", container: null, printings: {} };
  return { ...packFilingRule(order, order.rule),
    container: typeof order.container === "string" && order.container ? order.container : null,
    sleeved: order.sleeved === true, // slice 6: Put back drops "unsleeved" for a sleeved default container
    printings: order.printings && typeof order.printings === "object" ? order.printings : {},
    filedSections: new Map(Object.entries(order.filed_sections || {})), ...packStorageContainers(order) };
}

/** A container's divisions and the physical sequence in which to visit its sections. */
function packFilingRule(container, rule) {
  return { rule: ["colour-type", "set", "name", "none"].includes(rule) ? rule : "none",
    sections: storageGroupSections(container.sections),
    sectionOrder: Array.isArray(container.section_order) ? container.section_order : [] };
}

/** Containers and recorded placement when the plan distinguishes cards inside and outside a container. */
function packStorageContainers(order) {
  const list = Array.isArray(order.containers) ? order.containers.filter(c => c && typeof c.id === "string"
    && typeof c.name === "string") : [];
  if (!list.length) return { containers: null, placed: {} };
  return { containers: list.map(c => ({ id: c.id, name: c.name, ...packFilingRule(c, c.order) })),
    placed: order.placed && typeof order.placed === "object" ? order.placed : {} };
}

/** A single set-ordered container keeps its familiar label. Other physical divisions offer Storage order. */
function packOrderOptions(view) {
  const { containers, rule, sectionOrder } = view.storageRule;
  let label;
  if (!containers && rule === "set") label = "Set order";
  else if (containers || rule === "colour-type" || sectionOrder?.length) label = "Storage order";
  return label ? [["name", "Name"], ["storage", label]] : [["name", "Name"]];
}

/** The order the plan is drawn in: the person's choice, when the storage still offers it. */
function packOrder(view) {
  return view.order === "storage" && packOrderOptions(view).length > 1 ? "storage" : "name";
}

/** Basic lands join the pull step, and token cards follow Put back, only in the colour-and-type order
 * (Q4: that rule files basics with the other lands). */
function packFilesBasics(view) {
  return packOrder(view) === "storage" && view.storageRule.rule === "colour-type";
}

/** A browser preference for this person. Reordering the displayed plan needs no new preview. */
function packOrderControls(view) {
  view.orderGroup = el("div", { class: "segmented", role: "group", "aria-label": "Card order" });
  view.orderLabel = el("span", { text: "Card order" });
  view.orderHelp = el("p", { class: "sub pack-order-help" });
  packOrderSync(view);
  return el("div", { class: "toolbar pack-sort" }, view.orderLabel, view.orderGroup, view.orderHelp);
}

/** The order buttons for the storage the plan was read with; Name alone isn't offered as a choice. */
function packOrderSync(view) {
  const options = packOrderOptions(view), shown = packOrder(view);
  const name = view.storageRule.container;
  const where = view.storageRule.containers ? "By where the cards are filed, then as each container is ordered"
    : name ? `As the ${typeof colLowerName === "function" ? colLowerName(name) : name} is ordered` : null;
  clear(view.orderGroup).append(...options.map(([value, label]) => el("button", { type: "button", text: label,
    "aria-pressed": String(shown === value), title: value === "storage" ? where : null,
    onclick: () => {
      if (!view.data || packOrder(view) === value) return;
      view.order = value;
      local.set(view.sortKey, value);
      renderAssemblyPlan(view, view.data);
    } })));
  view.orderGroup.hidden = view.orderLabel.hidden = options.length < 2;
  view.orderHelp.hidden = options.length < 2 || shown !== "storage";
  view.orderHelp.textContent = view.storageRule.containers
    ? "Grouped by container, then by its filing order." : where || "Grouped by the storage filing order.";
}

/** The set order's divider (E8-S25 slice 5): the set of home's copy filed in the default container,
 * as storage_order's printings say; cards without one last. Ranks sort as strings. */
function packSetGroup(view, name) {
  const printing = view.storageRule.printings[name];
  if (!Array.isArray(printing) || typeof printing[0] !== "string" || !printing[0]) return ["~", "No printing recorded"];
  const code = printing[0].toUpperCase();
  return [`0${code}`, `Set · ${code}`];
}

/** Collector numbers in number order ("9" before "10"), then the name. */
function packCollectorOrder(view, a, b) {
  const number = (name) => String((view.storageRule.printings[name] || [])[1] || "");
  return storageCollectorCompare(number(a), number(b)) || a.localeCompare(b);
}

/** Picture grids in name order, or under the storage order's dividers (colour-and-type: by mana value;
 * set: by collector number). Rows keep their tick ids. */
function packCardGroups(view, rows) {
  if (!rows.length) return null;
  const sorted = [...rows].sort((a, b) => a.name.localeCompare(b.name));
  if (packOrder(view) !== "storage") return packGrid(view, sorted);
  if (!view.storageRule.containers) return packRuleGroups(view, sorted, view.storageRule, "h4");
  return packContainerGroups(view, sorted);
}

function packGrid(view, rows) {
  return el("div", { class: "card-tiles pack-tiles" }, rows.map(row => packTile(view, row.name, row)));
}

/** Slice 7: a heading for each container holding some of the rows, in the setup's order, then
 * "Somewhere else" (locations no container matches); within each, that container's own rule. */
function packContainerGroups(view, sorted) {
  const { containers, placed, container: fallbackName } = view.storageRule;
  const fallback = containers.find(c => c.name === fallbackName)?.id ?? null;
  const groups = new Map([...containers.map(c => [c.id, { ...c, rows: [] }]),
    [null, { unmatched: true, name: "Somewhere else", rule: "name", sections: {}, rows: [] }]]);
  for (const row of sorted) {
    const id = Object.hasOwn(placed, row.name) ? placed[row.name] : fallback;
    (groups.get(id) || groups.get(null)).rows.push(row);
  }
  return [...groups.values()].filter(group => group.rows.length).map(group => {
    const count = group.rows.reduce((total, row) => total + row.qty, 0);
    return el("div", { class: "pack-container-group" },
      el("h4", {}, group.name, el("span", { class: "pack-section-count", text: ` · ${plural(count, "card")}` })),
      el("p", { class: "pack-container-remaining", "data-pack-remaining": "" }),
      group.unmatched ? el("p", { class: "sub", text: "These cards match no configured storage container, or have no recorded location and no default container." }) : null,
      packRuleGroups(view, group.rows, group, "h5"));
  });
}

/** Visit the physical sections in order, then each section's colour/type or set dividers. */
function packRuleGroups(view, sorted, container, heading) {
  const { rule, sectionOrder, sections } = container;
  const bySet = rule === "set";
  const groups = new Map();
  for (const row of sorted) {
    const [rank, label] = bySet ? packSetGroup(view, row.name)
      : rule === "colour-type" ? storageCardGroup(view.cards[row.name]) : [0, ""];
    const section = view.storageRule.filedSections?.get(row.name) ?? (rule === "colour-type" ? sections?.[storageGroupKind(rank)] : null);
    const title = [section, label].filter(Boolean).join(" · ");
    const key = JSON.stringify([section || null, rank]);
    if (!groups.has(key)) groups.set(key, { rank, section: storageSectionRank(sectionOrder, section), title, rows: [] });
    groups.get(key).rows.push(row);
  }
  const ordered = [...groups.values()].sort((a, b) => a.section - b.section || (a.rank < b.rank ? -1 : a.rank > b.rank ? 1 : 0));
  return ordered.map(group => {
    if (bySet) group.rows.sort((a, b) => packCollectorOrder(view, a.name, b.name));
    if (rule === "colour-type") group.rows.sort((a, b) => storageManaValue(view.cards[a.name]) - storageManaValue(view.cards[b.name])
      || a.name.localeCompare(b.name));
    const grid = packGrid(view, group.rows);
    if (!group.title && groups.size === 1) return grid;
    const count = group.rows.reduce((total, row) => total + row.qty, 0);
    return el("div", { class: "pack-storage-group" },
      el(heading, {}, group.title || "No section recorded",
        el("span", { class: "pack-section-count", text: ` · ${plural(count, "card")}` })), grid);
  });
}

/** A Ref's name in a sentence: its label when it's in the accessories list, else the text as written. */
function assemblyKitName(ref) { return ref.state === "linked" ? ref.label : `“${ref.value}”`; }

/** Show sleeves and the box together before pulling cards. The existing kit picker owns assignment. */
function assemblyKit(deck, need, view = null) {
  if (!mayDo("see_accessories")) return null;      // kit isn't shown to someone who sees none
  const kit = deck.kit;
  const choice = view?.choices.find(c => c.id === deck.id);
  const canChoose = choice && holdsKit(choice.status) && deck.completion?.editable !== false && kit?.editable !== false
    && mayDo("accessories");
  const rows = [["sleeves", "Sleeves"], ["deck_box", "Deck box"]].map(([field, title]) => {
    const ref = kit?.[field];
    const name = ref ? assemblyKitName(ref) : (field === "sleeves" ? deck.sleeves : null) || "Not recorded";
    let fit = null;
    if (ref?.state === "linked") {
      if (field === "sleeves" && need != null) fit = `${need} needed, ${ref.quantity} owned`;
      else if (ref.capacity != null) fit = `holds ${plural(ref.capacity, "card")}`;
    }
    const change = canChoose && !ref ? el("button", { type: "button", class: "btn", text: field === "sleeves" ? "Choose sleeves" : "Choose a deck box",
      onclick: event => {
        if (!event.currentTarget.isConnected || !assemblyActive(view) || view.hash !== location.hash
            || !view.data?.decks.includes(deck) || view.previewing || view.saving || view.reviewing) return;
        kitPicker({ holder: deck.id, field, need, title: deck.title, onPicked: () => {
          if (assemblyActive(view) && view.hash === location.hash && view.data?.decks.includes(deck)) view.run();
        } });
      } }) : null;
    return el("div", { class: "pack-kit-row" }, accessoryThumb(ref || { label: title }, 64),
      el("p", { text: [`${title}: ${name}`, fit].filter(Boolean).join(" · ") }), change);
  });
  return el("div", { class: "assembly-kit" }, rows,
    !canChoose && deck.completion?.editable && (!kit?.sleeves || !kit?.deck_box)
      ? el("p", { class: "sub", text: "Review sleeves and box at Finish building." }) : null,
    String(deck.id).startsWith("product/") ? el("a", { class: "btn btn-quiet", href: deckHref(deck.id, deck.version),
      text: "Review this product’s kit" }) : null,
    warningsBox(kit?.warnings || [], "Sleeves or box to check"));
}

/** One step of a deck's plan: a numbered heading (number null: an optional step, with none) and its
 * content; nothing when it has none. */
function packStep(number, title, ...content) {
  const parts = content.flat(Infinity).filter(Boolean);
  if (!parts.length) return null;
  const optional = number === null;
  return el("details", { class: optional ? "pack-step is-optional" : "pack-step" },
    el("summary", { class: "pack-step-summary" },
      el("h3", {}, el("span", { class: "pack-step-n", "aria-hidden": "true", text: optional ? "" : String(number) }),
        el("span", { class: "pack-step-spoken sr-only", text: optional ? "Optional step. " : `Step ${number}. ` }), title),
      el("span", { class: "pack-step-chevron", "aria-hidden": "true" })),
    el("div", { class: "pack-step-body" }, parts));
}

/** A deck's plan, step by step. */
function packDeck(view, deck) {
  const usable = (ref) => ref && ref.state !== "kind_mismatch" ? ref : null;     // a wrong-kind value gets no tick
  const kit = mayDo("see_accessories") ? deck.kit : null;
  const sleeves = usable(kit && kit.sleeves), box = usable(kit && kit.deck_box);
  const need = !kit ? null : deck.sleeves_need != null ? deck.sleeves_need : kit.need;
  const steps = deck.steps || [];
  const participant = { id: deck.id, version: deck.version };
  const tiles = (rows) => packCardGroups(view, rows);
  const pulls = steps.filter(s => s.storage).map(s => ({ name: s.name, qty: s.storage, meta: packLocationMeta(view, s.name), finishes: deck.finishes?.[s.name],
    caption: `Pull ${s.storage} from storage for ${deck.title}`, id: `pull|${s.name}`, overlap: participant,
    printing: deck.completion?.already_built ? null : packPrintingControl(view, deck, s.name, s.storage) }));
  const moves = steps.flatMap(s => s.transfers.map(t => ({ name: s.name, qty: t.quantity, meta: `From ${t.from_title}`, finishes: deck.finishes?.[s.name],
    caption: `Move ${t.quantity} from ${t.from_title} to ${deck.title}; change sleeves`, id: `move|${s.name}|${t.from}`, overlap: participant })));
  const basics = (deck.basics || []).map(b => ({ name: b.name, qty: b.quantity, meta: null, finishes: deck.finishes?.[b.name],
    caption: `${b.quantity} for ${deck.title}`, id: `basic|${b.name}` }));
  const markers = (deck.standins?.rows || []).filter(row => !row.using).map((row, index) => ({
    name: row.for, qty: row.qty, meta: "Use any spare card",
    caption: `Pack ${plural(row.qty, "spare card")} for ${row.for} in ${deck.title}`, id: `standin|${row.for}|${index}` }));
  const returns = (deck.returns || []).map(r => ({ name: r.name, qty: r.quantity, meta: r.untracked ? null : packLocationMeta(view, r.name),
    label: r.untracked ? r.name.replace(/^Spare stand-in for /, "Physical placeholder for ") : r.name,
    caption: `Return ${r.quantity} from ${deck.title} to storage`, id: `return|${r.name}` }));
  const kept = steps.filter(s => s.keep);
  const waiting = steps.filter(s => s.waiting || s.missing);
  const tokenParts = [...(assemblyTokenTasks(deck.tokens, view.data.tokens, view) || []),
    !deck.tokens?.error && !deck.tokens?.unavailable ? assemblyCounterTasks(view.data.counters, deck.id) : null];
  let n = 0;
  const step = (kind, title, ...content) => {
    const node = packStep(n + 1, title, ...content);
    if (node) { packRegisterStep(view, deck, kind, n + 1, node); n += 1; }
    return node;
  };
  // Tokens are never required: no number in the sequence, and nothing here counts towards finishing.
  const tokenStep = () => {
    if (!tokenParts.some(Boolean)) return null;
    const node = packStep(null, "Tokens (optional)", tokenParts,
      el("a", { class: "btn btn-quiet", href: "#/tokens", text: "Manage token cards" }));
    if (node) packRegisterStep(view, deck, "tokens", null, node);
    return node;
  };
  const cardStep = (kind, title, rows, ...intro) => {
    const count = rows.reduce((total, row) => total + row.qty, 0);
    return rows.length ? step(kind, `${title} (${plural(count, "card")})`, ...intro, tiles(rows)) : null;
  };
  const kitNode = assemblyKit(deck, need, view);
  const keptNode = kept.length ? el("details", { class: "pack-fold" },
    el("summary", { text: `Keep in this box (${plural(kept.reduce((s, k) => s + k.keep, 0), "card")})` }),
    el("ul", { class: "pack-plain" }, kept.map(k => el("li", { text: `${k.keep} × ${k.name}` })))) : null;
  return el("section", { class: "panel pack-deck", "data-pack-deck": `${deck.id}:${deck.version}` },
    el("div", { class: "pack-deck-head" },
      el("h2", {}, el("a", { href: deckHref(deck.id, deck.version), text: deck.title })),
      el("p", { class: "sub", text: `Packing the ${listName(deck.version, true)}` }),
      deck.build_scope ? el("p", { class: "sub pack-build-scope", text: packScopeWords(deck) }) : null,
      packCurrentBox(view, deck)),
    packBulkControl(view, deck),
    packStandinsPart(view, deck),
    step("sleeves", "Sleeves and deck box", kitNode, sleeves && need ? el("ul", { class: "pack-list" },
      assemblyTick(`Get out ${need} ${assemblyKitName(sleeves)} sleeves`, 1, [sleeves.id || sleeves.value, need], "sleeves")) : null),
    cardStep("pull", "Pull from storage", packFilesBasics(view) ? [...pulls, ...basics] : pulls, pulls.length ? packLocationNote(view) : null),
    cardStep("move", "Move from other decks", moves, el("p", { class: "sub", text: "Change their sleeves as you move them." })),
    !packFilesBasics(view) ? cardStep("basic", "Basic lands", basics) : null,
    cardStep("standin", "Physical placeholders", markers),
    !packFilesBasics(view) ? tokenStep() : null,
    cardStep("return", "Return to storage", returns, el("p", { class: "sub", text: `Return these from ${deck.title} to storage${view.storageRule.sleeved ? "" : ", unsleeved"}.` })),
    packFilesBasics(view) ? tokenStep() : null,
    step("box", "Pack", box ? el("ul", { class: "pack-list" },
      assemblyTick(`Pack into ${assemblyKitName(box)}`, 1, [box.id || box.value], "box")) : null),
    keptNode,
    remainingIntentPart(deck.remaining_intent),
    waiting.length ? el("details", { class: "pack-fold pack-waiting" },
      el("summary", { text: `Copies to check (${plural(waiting.reduce((s, w) => s + w.waiting + w.missing, 0), "card")})` }),
      el("ul", { class: "pack-plain" }, waiting.flatMap(w => [
        w.waiting ? el("li", { class: "assembly-pending", text: `On the way: ${w.waiting} × ${w.name}` }) : null,
        w.missing ? el("li", { class: "assembly-pending", text: `To check: ${w.missing} × ${w.name}` }) : null]))) : null);
}

function packCurrentBox(view, deck) {
  if (deck.completion?.status !== "built") return null;
  const info = packTakeApartContents(deck.take_apart);
  const version = info?.version || deck.completion.built_version;
  const count = info ? plural(info.card_count, "physical card") : "";
  const checked = boxCheckDate(deck.box_check?.checked_on);
  return el("div", { class: "pack-current-box" },
    el("h3", { text: "Packed in this box" }),
    version ? el("p", { text: [listName(version), count].filter(Boolean).join(" · ") }) : null,
    checked ? el("p", { class: "sub" }, "Last checked ", el("time", { datetime: checked, text: checked })) : null,
    el("div", { class: "actions" }, packBoxCheckButton(view, deck), packTakeApartButton(view, deck)),
    packBoxCheckDraftFor(deck) && !packBoxCheckCanResume(deck) ? el("p", { class: "sub",
      text: "The paused count could not be matched to this box. Start a fresh check." }) : null);
}

function renderAssemblyPlan(view, data) {
  const presentation = packSwitcherBeforeRender(view);
  packClearBar(view);
  packPreferenceBeforeRender(view);
  clear(view.results);
  view.data = data;
  packStepsStart(view, data);
  packOverlapStart(view, data);
  view.bulk = [];
  view.finish = null;
  view.cards = data.cards || {};
  view.storageRule = packStorageRule(data);
  packOrderSync(view);
  view.sortControl.hidden = !data.decks.length;
  if (!data.decks.length) {
    packAttachSwitcher(view, data, []);
    wirePackTicks(view);
    view.results.append(el("div", { class: "empty" }, el("p", { text: "Choose the decks you want to play." }),
      el("button", { type: "button", class: "btn", text: "Choose decks", onclick: () => {
        packRevealChooser(view);
      } })));
    packSwitcherAfterRender(view, presentation);
    return;
  }
  const standins = data.decks.reduce((sum, deck) => sum + (deck.standins?.rows || []).reduce((n, row) => n + row.qty, 0), 0);
  const statusText = data.list_issue || (!data.counts_confirmed ? "Resolve the inventory warnings before relying on this plan."
    : data.ready ? standins ? `Ready to pack with ${plural(standins, "physical placeholder")}. Check the cards before finishing.`
      : "Every card is here. Pull them below."
    : [data.totals.waiting ? `${plural(data.totals.waiting, "copy", "copies")} still on the way` : null,
      data.totals.missing ? `${plural(data.totals.missing, "copy", "copies")} not available for this plan` : null]
      .filter(Boolean).join("; ") + ".");
  add(view.results, [el("p", { class: data.ready ? "box box-good" : "box box-warn", text: statusText }),
    warningsBox(data.warnings, "Inventory needs attention"), packOverlapNotice(view),
    // Decks in the same sleeves (one design may sleeve several decks): a note, never a block.
    (data.sleeve_notes || []).length ? el("div", { class: "pack-sleeve-notes" },
      note(...data.sleeve_notes.map((n) => n.note))) : null]);
  if (data.unresolved.length) view.results.append(el("p", { class: "box box-warn",
    text: `Unresolved card names: ${data.unresolved.join(", ")}` }));
  const panels = data.decks.map(deck => ({ deck, node: packDeck(view, deck) }));
  view.results.append(packAttachSwitcher(view, data, panels), el("div", { class: "pack-decks" }, panels.map(panel => panel.node)));
  const completion = packCompletion(view, data);
  if (completion) view.results.append(completion);
  const held = data.rows.filter(row => row.missing).map(row => ({ ...row,
    held_elsewhere: (row.held_elsewhere || []).filter(holder => !packIntactProduct(holder)) })).filter(row => row.held_elsewhere.length);
  if (held.length) view.results.append(el("section", { class: "panel pack-extra" }, el("h2", { text: "Held in another deck" }),
    el("p", { text: "These decks keep their cards. Add a donor deck with its revised saved list to plan a transfer." }),
    el("ul", {}, held.map(row => el("li", {}, `${row.name}: `,
      row.held_elsewhere.map((holder, index) => [index ? "; " : "", `${holder.quantity} in `,
        el("a", { href: deckHref(holder.id), text: holder.title })]))))));
  add(view.results, [packIntactProductsPart(view, data)]);
  add(view.results, [assemblyTakeAlong(view, data)]);
  add(view.results, [assemblyTokenProblems(data.token_problems), assemblySharedTokens(data), assemblyTokenPanel(data)]);
  view.results.append(el("p", { class: "sub", text: data.note }));
  view.bar = packBuildBar(view);
  view.planMain.append(view.bar.node);
  wirePackTicks(view);
  packSwitcherAfterRender(view, presentation);
}

/** Finish here: ticks record progress; this explicit action saves the assembled lists. */
function packCompletion(view, data) {
  const completion = data.completion;
  if (!completion) return null;
  const count = completion.decks.length;
  const firstScope = data.decks.find(deck => deck.id === completion.decks[0]?.id)?.build_scope;
  const label = count > 1 ? `Mark ${count} decks built` : firstScope?.mode === "main" ? "Mark main deck built"
    : firstScope?.mode === "partial" ? "Mark selected cards built" : "Mark as built";
  const message = el("p", { class: "pack-completion-message", role: "status", tabindex: "-1", id: `pack-finish-${++packFinishSerial}` });
  const error = el("div", { class: "pack-completion-error", role: "alert" });
  const button = count ? el("button", { type: "button", class: "btn btn-primary pack-built", text: label,
    "aria-describedby": message.id, onclick: event => packFinishClick(view, event.currentTarget) }) : null;
  view.finish = { message, error, button, label, data };
  packFinishError(view);
  if (!count && !view.finishError && !data.buildWarnings?.length && !data.tableRefreshError) return null;
  return el("section", { class: "panel pack-completion" }, el("h2", { text: "Finish building" }),
    count ? el("p", { class: "sub", text: "Marking built records the cards now in each box and reserves them for these decks: "
      + completion.decks.map(d => {
        const scope = data.decks.find(deck => deck.id === d.id)?.build_scope;
        return `${d.title} (${listName(d.version)}${scope ? `; ${scope.label}` : ""})`;
      }).join(", ") + "." }) : null,
    warningsBox(data.buildWarnings || [], "Built, with notes"),
    data.tableRefreshError ? tablesLaterNote("Some availability tables could not be updated.") : null, error);
}

function packFinishError(view) {
  if (!view.finish) return;
  clear(view.finish.error);
  if (view.finishError) view.finish.error.append(el("p", { text: view.finishError }),
    el("button", { type: "button", class: "btn", text: "Refresh plan", onclick: () => {
      view.finishError = null;
      view.builtMessage = null;
      view.run();
    } }));
}

function packCanFinish(view) {
  return Boolean(view.data?.completion?.can_mark_built && view.data.completion.decks.length
    && !view.previewing && !view.saving && !view.reviewing && !view.finishError
    && view.progress?.loaded && !packUnsavedTicks(view) && !packProgressFailed(view)
    && (view.ticks || []).filter(t => t.tile).every(t => t.done));
}

/** The list choices and ticks stay still while this one save is in flight. Navigation remains available. */
function packSaving(view, saving) {
  view.saving = saving;
  if (saving) {
    view.saveDisabled = ["button", "input", "select"].flatMap(tag => [...view.root.querySelectorAll(tag)])
      .filter(node => !node.disabled && node !== view.finish?.button && !view.chooser.contains(node));
    view.saveDisabled.forEach(node => { node.disabled = true; });
  } else {
    (view.saveDisabled || []).forEach(node => { node.disabled = false; });
    view.saveDisabled = [];
  }
  packProgress(view);
}

async function packMarkBuilt(view) {
  if (!assemblyActive(view) || !packCanFinish(view)) return;
  const data = view.data, finish = view.finish;
  const selected = view.selected.map(item => ({ ...item }));
  clear(finish.error);
  let review = null;
  if (data.completion.review) {
    view.reviewing = true; packProgress(view);
    review = await packReviewBuilt(view);
    view.reviewing = false;
    if (!assemblyActive(view) || view.data !== data) return;
    packProgress(view);
    if (!review || !packCanFinish(view)) return;
  }
  const printings = packPrintingsBody(view, data);
  packSaving(view, true);
  try {
    const answer = await apiWrite("/api/assembly/built", { decks: selected,
      fingerprint: data.completion.fingerprint, confirmed: true, ...(review ? { kit: review.kit } : {}),
      ...(Object.keys(printings).length ? { printings } : {}) });
    if (!assemblyActive(view) || view.data !== data) return;
    packSaving(view, false);
    const updated = answer.plan;
    // Keep the checked checklist in sight; a fresh allocation would make those completed pulls disappear.
    const buildWarnings = [...(answer.warnings || [])];
    if (answer.tables?.error) buildWarnings.push(`The decks were marked built, but their availability tables could not be updated: ${answer.tables.error}`);
    const kept = { ...data, completion: updated.completion, buildWarnings, tableRefreshError: !!answer.tables?.error,
      box_check_cards: updated.box_check_cards, take_along: updated.take_along,
      decks: data.decks.map(deck => {
        const saved = updated.decks.find(d => d.id === deck.id);
        return { ...deck, ...(saved ? { completion: saved.completion, standins: saved.standins,
          kit: saved.kit, sleeves: saved.sleeves, sleeves_need: saved.sleeves_need,
          build_scope: saved.build_scope, remaining_intent: saved.remaining_intent,
          take_apart: saved.take_apart, box_check: saved.box_check } : {}) };
      }) };
    view.buildKit = {};
    view.boxPrintings = {};
    const built = new Set(answer.built.map(deck => deck.id));
    view.choices = view.choices.map(choice => built.has(choice.id) ? { ...choice, status: "built" } : choice);
    view.finishError = null;
    view.builtMessage = answer.built.length === 1 ? `${answer.built[0].title} is now marked built.`
      : `${answer.built.length} decks are now marked built.`;
    drawPackPicks(view);
    renderAssemblyPlan(view, kept);
    showToast(view.builtMessage);
  } catch (problem) {
    if (!assemblyActive(view) || view.data !== data) return;
    packSaving(view, false);
    view.finishError = problem.message;
    packFinishError(view);
    packProgress(view);
  }
}

/** All participants contribute copies; kit steps keep their own unit, and token ticks are in neither. */
function packProgress(view) {
  packChooserSync(view);
  packViewerSync(view);
  packOpenRequestedBoxCheck(view);
  for (const group of view.results?.querySelectorAll(".pack-container-group") || []) {
    const remaining = (view.ticks || []).filter(t => t.tile && !t.done && group.contains(t.node))
      .reduce((total, t) => total + t.count, 0);
    const label = group.querySelector("[data-pack-remaining]");
    if (label) label.textContent = remaining ? `${plural(remaining, "card")} left in this step` : "All cards in this group ticked";
  }
  if (!view.bar) return;
  packBulkProgress(view);
  const ticks = view.ticks || [];
  packUpdateBar(view, ticks.filter(t => !t.optional), ticks.filter(t => t.tile), ticks.filter(t => !t.tile && !t.optional));
  const clearButton = view.bar.node.querySelector(".pack-clear");
  if (clearButton) clearButton.disabled = Boolean(view.saving) || !ticks.some(t => t.done);
}
