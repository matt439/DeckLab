/* The packing plan (UI-REVIEW.md WP10, INV-4, INV-5): choose the decks that need to exist together from a
checklist, and the plan (POST /api/assembly/preview, which writes nothing) is worked out at once. Each deck's
plan is grouped into steps: sleeves; pull from storage; move from other decks; basics; tokens; put back; pack;
with what's still waiting folded at the end. Cards are picture tiles, each with a tick, and every picture opens
the card viewer over the whole plan ("packing"). A sticky bar says how far the packing has got ("Pulled 12 of
31 cards"); the ticks are shared through the server (assembly-progress.js) and never reserve or change
inventory. Each deck's sleeves and deck box (its "kit") use accessories.js's accessoryThumb() and, where none
are recorded, its kitPicker(); decks chosen together that share one design of sleeves get a note (sleeve_notes),
never a block. Each deck's tokens come from the server's deck_tokens (lib/tokens). Once the card tasks are
checked, Mark as built saves the selected lists together; ticks alone never change the deck's status. */
"use strict";

const PACK_MAX = 12;                    // decks in one plan (lib/api/assembly.py MAX_DECKS)
const PACK_DELAY = 250;                 // ms after a change before the plan is worked out again
const PACK_GROUPS = [["built", "Built"], ["building", "Being built"], ["idea", "Ideas"], ["product", "Products"]];

function showAssembly(params, token) {
  const query = new URLSearchParams();
  const id = params.get("deck") || params.get("id");
  if (id) { query.set("deck", id); query.set("version", params.get("version") || "target"); }
  return load(`/api/assembly?${query}`, token, data => drawAssembly(data, token));
}

/** The group a deck choice is listed under: its status, or "product" for a product's decks. */
function packGroupOf(choice) {
  if (String(choice.id).startsWith("product/")) return "product";
  return ["built", "building"].includes(choice.status) ? choice.status : "idea";
}

function drawAssembly(data, token) {
  const sortKey = `packing-order.${state.profile?.id || "guest"}`;
  const view = { token, profile: state.profile?.id, choices: data.choices.filter(item => !item.error && item.versions?.length),
    selected: (data.selections || data.decks).map(packSelectedChoice), seq: 0, timer: null,
    sortKey, order: local.get(sortKey) === "storage" ? "storage" : "name" };
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
  view.chooserEmpty = el("p", { class: "sub pack-chooser-empty", text: "No decks available for this plan." });
  view.chooser.append(view.chooserEmpty);
  view.chooserLaunch = el("button", { type: "button", class: "btn pack-chooser-launcher", text: "Decks",
    "aria-haspopup": "dialog", "aria-expanded": "false", onclick: () => packRevealChooser(view) });
  view.chooserRail = el("div", { class: "pack-chooser-rail" });
  view.chooserSlot = el("div", { class: "pack-chooser-slot" }, view.chooserRail);
  view.planMain = el("div", { class: "pack-main" }, view.chooserLaunch, view.messageSlot, view.progressNote, view.sortControl, view.results);
  add(view.root, [
    pageHead({ crumb: fromDeck ? [deckHref(fromDeck.id, parseHash().params.get("version")), fromDeck.title || "The deck"] : null,
      title: routeH1("assembly"), description: "Choose the decks you want to play, then pull their cards. Each physical copy is counted once.",
      // The plan's sleeves and token cards come from these pages.
      more: [mayDo("see_accessories") ? { label: routeFor("accessories").label, href: "#/accessories" } : null,
        { label: routeFor("tokens").label, href: "#/tokens" }] }),
    el("div", { class: "pack-layout" }, view.chooserSlot, view.planMain)]);
  $("#main").append(view.root);
  view.run = () => packRun(view);
  packInitChooser(view);
  packInitSwitcher(view);
  drawPackPicks(view);
  renderAssemblyPlan(view, data);
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
  view.message.textContent = view.selected.length ? "Working out the plan…" : "";
  try {
    const result = await apiWrite("/api/assembly/preview", { decks: view.selected.map(item => ({ ...item })) });
    if (!assemblyActive(view) || seq !== view.seq) return;
    view.previewing = false;
    view.builtMessage = null;
    view.finishError = null;
    view.message.textContent = "";
    if (result.selections) {
      view.selected = result.selections.map(packSelectedChoice);
      drawPackPicks(view);
    }
    renderAssemblyPlan(view, result);
  } catch (problem) {
    if (assemblyActive(view) && seq === view.seq) {
      view.previewing = false;
      view.message.textContent = problem.message;
      packClearBar(view);
      clear(view.results);
      view.sortControl.hidden = true;
      view.data = null;
      view.finish = null;
      view.bar = null;
      wirePackTicks(view);
    }
  }
}

/** A tick in a list; physical context distinguishes kit or token variants with the same label. */
function assemblyTick(text, count = 1, context = null, key = text) {
  return el("li", {}, el("label", { class: "pack-row" },
    el("input", { type: "checkbox", "data-pack-tick": key, "data-pack-count": count,
      "data-pack-context": context ? JSON.stringify(context) : "" }), el("span", { text })));
}

/** A card to pull as a picture tile with a tick on its corner; id is its key for the saved ticks. */
function packTile(view, name, { qty, meta, caption, id, finishes = [] }) {
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
    "aria-label": `${qty > 1 ? `${qty} × ` : ""}${name}: done`, "data-pack-tick": id, "data-pack-count": qty,
    "data-pack-context": JSON.stringify(finishes.map(f => [f.finish, f.quantity]).sort()) });
  const tile = cardTile(card, { qty, name: frontName(name), meta, finish, chips, state: tick,
    onclick: card ? event => packOpenCard(view, event.currentTarget) : null,
    viewerGroup: "packing", caption: description, label: finishWords ? `${name}. ${description}` : card ? null : name });
  packRegisterCard(view, tile, card, description);
  return tile;
}

/** A browser preference for this person. Reordering the displayed plan needs no new preview. */
function packOrderControls(view) {
  const options = [["name", "Name"], ["storage", "Storage order"]];
  const group = el("div", { class: "segmented", role: "group", "aria-label": "Card order" });
  for (const [value, label] of options) {
    group.append(el("button", { type: "button", text: label, "aria-pressed": String(view.order === value),
      onclick: () => {
        if (!view.data || view.order === value) return;
        view.order = value;
        local.set(view.sortKey, value);
        Array.from(group.children).forEach((button, i) => button.setAttribute("aria-pressed", String(options[i][0] === value)));
        renderAssemblyPlan(view, view.data);
      } }));
  }
  return el("div", { class: "toolbar pack-sort" }, el("span", { text: "Card order" }), group);
}

/** The storage rows: creatures (artifacts last), spells (artifacts last), then lands by mana colour.
 * Nonlands use the front's colours, never Commander identity. Colourless non-artifacts follow
 * multicolour in their row; missing card data stays visible at the end. */
function packStorageGroup(card) {
  const face = card?.faces?.[0] || card;
  const type = (face?.type_line || card?.type_line || "").split(" // ")[0].split(/\s[—–-]\s/)[0];
  if (!type) return [23, "Other cards"];
  const colored = values => (values || []).filter(c => "WUBRG".includes(c));
  const rank = colors => colors.length > 1 ? 5 : colors.length ? "WUBRG".indexOf(colors[0]) : 6;
  const words = ["White", "Blue", "Black", "Red", "Green", "Multicolour", "Colourless"];
  if (/\bLand\b/.test(type)) {
    const produces = colored(card.produced_mana);
    const color = rank(produces.length ? produces : colored(card.color_identity));
    return [16 + color, `Lands · ${words[color]}`];
  }
  const creature = /\bCreature\b/.test(type);
  if (/\bArtifact\b/.test(type)) return creature ? [7, "Artifact creatures"] : [15, "Artifacts"];
  const color = rank(colored(face.colors ?? card.colors));
  return [color + (creature ? 0 : 8), `${creature ? "Creatures" : "Spells"} · ${words[color]}`];
}

/** Unknown mana values sort after known costs, including zero. */
function packManaValue(card) {
  return Number.isFinite(card?.cmc) ? card.cmc : Infinity;
}

/** Picture grids in name order, or by mana value under the storage dividers. Rows keep their tick ids. */
function packCardGroups(view, rows) {
  if (!rows.length) return null;
  const grid = (items) => el("div", { class: "card-tiles pack-tiles" },
    items.map(row => packTile(view, row.name, row)));
  const sorted = [...rows].sort((a, b) => a.name.localeCompare(b.name));
  if (view.order !== "storage") return grid(sorted);
  const groups = new Map();
  for (const row of sorted) {
    const [rank, label] = packStorageGroup(view.cards[row.name]);
    if (!groups.has(rank)) groups.set(rank, { label, rows: [] });
    groups.get(rank).rows.push(row);
  }
  return [...groups].sort(([a], [b]) => a - b).map(([, group]) => {
    group.rows.sort((a, b) => packManaValue(view.cards[a.name]) - packManaValue(view.cards[b.name])
      || a.name.localeCompare(b.name));
    const count = group.rows.reduce((total, row) => total + row.qty, 0);
    return el("div", { class: "pack-storage-group" },
      el("h4", {}, group.label, el("span", { class: "pack-section-count", text: ` · ${plural(count, "card")}` })),
      grid(group.rows));
  });
}

/** A Ref's name in a sentence: its label when it's in the accessories list, else the text as written. */
function assemblyKitName(ref) { return ref.state === "linked" ? ref.label : `“${ref.value}”`; }

/** A deck panel's sleeves: a 64 px picture and "Sleeve with Dragon Shield Matte (black): 75 needed, 100
 * owned", and the kit's warnings (too few sleeves, a deck box too small) in a box under it. A deck with
 * none recorded gets Choose sleeves (accessories.js kitPicker) when it's built and the visitor may choose,
 * else a link to the deck. view (optional): the plan, worked out again once sleeves are chosen. */
function assemblyKit(deck, need, view = null) {
  if (!mayDo("see_accessories")) return null;      // the home's sleeves aren't shown to a person-space profile
  const kit = deck.kit, sleeves = kit && kit.sleeves;
  let words = `Sleeves: ${deck.sleeves || "Not recorded"}`;
  let action = null;
  if (sleeves && sleeves.state === "linked") {
    words = `Sleeve with ${sleeves.label}: ${need} needed, ${sleeves.quantity} owned`;
  } else if (sleeves && sleeves.state === "text") {
    words = `Sleeves: ${assemblyKitName(sleeves)} (not in the accessories list)` + (need ? `, ${need} needed` : "");
  } else {
    const choice = view && (view.choices || []).find(c => c.id === deck.id);
    const built = choice && choice.status === "built";
    action = built && mayDo("accessories") && typeof kitPicker === "function"
      ? el("button", { type: "button", class: "btn", text: "Choose sleeves", onclick: () => kitPicker({ holder: deck.id,
        field: "sleeves", need, title: deck.title, onPicked: () => { if (view && view.run) view.run(); } }) })
      : String(deck.id).startsWith("product/") ? el("a", { class: "btn btn-quiet", href: "#/accessories", text: "Choose sleeves" })
        : el("a", { class: "btn btn-quiet", href: deckHref(deck.id, deck.version), text: built ? "Choose on the deck page" : "Open the deck" });
  }
  return el("div", { class: "assembly-kit" },
    el("div", { class: "pack-kit-row" }, accessoryThumb(sleeves || { label: "Sleeves" }, 64), el("p", { text: words }), action),
    kit && kit.warnings && kit.warnings.length
      ? el("div", { class: "box box-warn" }, el("ul", {}, kit.warnings.map((w) => el("li", { text: w })))) : null);
}

/** One step of a deck's plan: a numbered heading and its content; nothing when it has none. */
function packStep(number, title, ...content) {
  const parts = content.flat(Infinity).filter(Boolean);
  if (!parts.length) return null;
  return el("div", { class: "pack-step" }, el("h3", {}, el("span", { class: "pack-step-n", text: String(number) }), title), parts);
}

/** A deck's plan, step by step. */
function packDeck(view, deck) {
  const usable = (ref) => ref && ref.state !== "kind_mismatch" ? ref : null;     // a wrong-kind value gets no tick
  const kit = mayDo("see_accessories") ? deck.kit : null;
  const sleeves = usable(kit && kit.sleeves), box = usable(kit && kit.deck_box);
  const need = !kit ? null : deck.sleeves_need != null ? deck.sleeves_need : kit.need;
  const steps = deck.steps || [];
  const tiles = (rows) => packCardGroups(view, rows);
  const pulls = steps.filter(s => s.storage).map(s => ({ name: s.name, qty: s.storage, meta: null, finishes: deck.finishes?.[s.name],
    caption: `Pull ${s.storage} from storage for ${deck.title}`, id: `pull|${s.name}` }));
  const moves = steps.flatMap(s => s.transfers.map(t => ({ name: s.name, qty: t.quantity, meta: `From ${t.from_title}`, finishes: deck.finishes?.[s.name],
    caption: `Move ${t.quantity} from ${t.from_title} to ${deck.title}; change sleeves`, id: `move|${s.name}|${t.from}` })));
  const basics = (deck.basics || []).map(b => ({ name: b.name, qty: b.quantity, meta: null, finishes: deck.finishes?.[b.name],
    caption: `${b.quantity} for ${deck.title}`, id: `basic|${b.name}` }));
  const markers = (deck.standins?.rows || []).filter(row => !row.using).map((row, index) => ({
    name: row.for, qty: row.qty, meta: "Use any spare card",
    caption: `Use or keep ${row.qty} spare cards to stand for ${row.for}`, id: `standin|${row.for}|${index}` }));
  const returns = (deck.returns || []).map(r => ({ name: r.name, qty: r.quantity, meta: null,
    caption: `Take ${r.quantity} out of ${deck.title}`, id: `return|${r.name}` }));
  const kept = steps.filter(s => s.keep);
  const waiting = steps.filter(s => s.waiting || s.missing);
  const tokenLines = assemblyTokenTasks(deck.tokens, view.data.tokens);
  let n = 0;
  const step = (title, ...content) => {
    const node = packStep(n + 1, title, ...content);
    if (node) n += 1;
    return node;
  };
  const cardStep = (title, rows, ...intro) => {
    const count = rows.reduce((total, row) => total + row.qty, 0);
    return rows.length ? step(`${title} (${plural(count, "card")})`, ...intro, tiles(rows)) : null;
  };
  const kitNode = assemblyKit(deck, need, view);
  const keptNode = kept.length ? el("details", { class: "pack-fold" },
    el("summary", { text: `Already in this deck (${plural(kept.reduce((s, k) => s + k.keep, 0), "card")})` }),
    el("ul", { class: "pack-plain" }, kept.map(k => el("li", { text: `${k.keep} × ${k.name}` })))) : null;
  return el("section", { class: "panel pack-deck", "data-pack-deck": `${deck.id}:${deck.version}` },
    el("div", { class: "pack-deck-head" },
      el("h2", {}, el("a", { href: deckHref(deck.id, deck.version), text: deck.title })),
      el("p", { class: "sub", text: listName(deck.version) }),
      deck.build_scope ? el("p", { class: "sub pack-build-scope", text: packScopeWords(deck) }) : null,
      deck.completion?.already_built ? status("good", "Built") : null),
    packBulkControl(view, deck),
    packStandinsPart(view, deck),
    step("Sleeves", kitNode, sleeves && need ? el("ul", { class: "pack-list" },
      assemblyTick(`Get out ${need} ${assemblyKitName(sleeves)} sleeves`, 1, [sleeves.id || sleeves.value, need], "sleeves")) : null),
    cardStep("Pull from storage", view.order === "storage" ? [...pulls, ...basics] : pulls),
    cardStep("Move from other decks", moves, el("p", { class: "sub", text: "Change their sleeves as you move them." })),
    view.order !== "storage" ? cardStep("Basic lands", basics) : null,
    cardStep("Spare-card stand-ins", markers),
    view.order !== "storage" ? step("Tokens", tokenLines && tokenLines.length ? el("ul", { class: "pack-list" }, tokenLines) : null) : null,
    cardStep("Put back", returns, el("p", { class: "sub", text: "Take these out of the deck and put them back in storage, unsleeved." })),
    view.order === "storage" ? step("Tokens", tokenLines && tokenLines.length ? el("ul", { class: "pack-list" }, tokenLines) : null) : null,
    step("Pack", box ? el("ul", { class: "pack-list" },
      assemblyTick(`Pack into ${assemblyKitName(box)}`, 1, [box.id || box.value], "box")) : null),
    keptNode,
    remainingIntentPart(deck.remaining_intent),
    waiting.length ? el("details", { class: "pack-fold pack-waiting" },
      el("summary", { text: `Still waiting (${plural(waiting.reduce((s, w) => s + w.waiting + w.missing, 0), "card")})` }),
      el("ul", { class: "pack-plain" }, waiting.flatMap(w => [
        w.waiting ? el("li", { class: "assembly-pending", text: `Wait for ${w.waiting} × ${w.name}` }) : null,
        w.missing ? el("li", { class: "assembly-pending", text: `Unavailable: ${w.missing} × ${w.name}` }) : null]))) : null);
}

function renderAssemblyPlan(view, data) {
  const presentation = packSwitcherBeforeRender(view);
  packClearBar(view);
  clear(view.results);
  view.data = data;
  view.bulk = [];
  view.finish = null;
  view.cards = data.cards || {};
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
  const statusText = !data.counts_confirmed ? "Resolve the inventory warnings before relying on this plan."
    : data.ready ? standins ? `Ready to pack with ${plural(standins, "stand-in")}. Check the physical cards below.`
      : "Every card is here. Pull them below."
    : [data.totals.waiting ? `${plural(data.totals.waiting, "copy", "copies")} still on the way` : null,
      data.totals.missing ? `${plural(data.totals.missing, "copy", "copies")} not available for this plan` : null]
      .filter(Boolean).join("; ") + ".";
  add(view.results, [el("p", { class: data.ready ? "box box-good" : "box box-warn", text: statusText }),
    warningsBox(data.warnings, "Inventory needs attention"),
    // Decks in the same sleeves (one design may sleeve several decks): a note, never a block.
    (data.sleeve_notes || []).length ? el("div", { class: "pack-sleeve-notes" },
      note(...data.sleeve_notes.map((n) => n.note))) : null]);
  if (data.unresolved.length) view.results.append(el("p", { class: "box box-warn",
    text: `Unresolved card names: ${data.unresolved.join(", ")}` }));
  const panels = data.decks.map(deck => ({ deck, node: packDeck(view, deck) }));
  view.results.append(packAttachSwitcher(view, data, panels), el("div", { class: "pack-decks" }, panels.map(panel => panel.node)));
  const completion = packCompletion(view, data);
  if (completion) view.results.append(completion);
  const held = data.rows.filter(row => row.missing && row.held_elsewhere.length);
  if (held.length) view.results.append(el("section", { class: "panel pack-extra" }, el("h2", { text: "Copies reserved elsewhere" }),
    el("p", { text: "These decks keep their cards. Add a donor deck with its revised saved list to plan a transfer." }),
    el("ul", {}, held.map(row => el("li", {}, `${row.name}: `,
      row.held_elsewhere.map((holder, index) => [index ? "; " : "", `${holder.quantity} in `,
        el("a", { href: deckHref(holder.id), text: holder.title })]))))));
  add(view.results, [warningsBox(data.token_problems || [], "Some token rows can't be read"),
    assemblySharedTokens(data)]);
  const tokens = data.tokens || [];
  view.results.append(el("details", { class: "panel pack-extra assembly-token-list" },
    el("summary", { text: `All your token cards (${tokens.length})` }),
    data.token_note ? el("p", { class: "sub", text: data.token_note }) : null,
    tokens.length ? el("ul", { class: "pack-plain" }, tokens.map(item => el("li", { text:
      `${item.quantity} physical ${item.quantity === 1 ? "card" : "cards"}: ${item.front}${item.front_details ? ` (${item.front_details})` : ""}`
      + `${item.back ? ` / ${item.back}${item.back_details ? ` (${item.back_details})` : ""}`
        : /single-sided verified/i.test(item.notes || "") ? " / single-sided (verified)" : " / reverse not recorded"}`
      + `${item.notes ? `. ${item.notes}` : ""}` }))) : el("p", { text: "No physical tokens have been recorded." })));
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
  return el("section", { class: "panel pack-completion" }, el("h2", { text: "Finish building" }),
    count ? el("p", { class: "sub", text: "Marking built saves these lists and reserves their cards: "
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
    && view.progress?.loaded && !view.progress.pending.size && !view.progress.error
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
  packSaving(view, true);
  try {
    const answer = await apiWrite("/api/assembly/built", { decks: selected,
      fingerprint: data.completion.fingerprint, confirmed: true, ...(review ? { kit: review.kit } : {}) });
    if (!assemblyActive(view) || view.data !== data) return;
    packSaving(view, false);
    const updated = answer.plan;
    // Keep the checked checklist in sight; a fresh allocation would make those completed pulls disappear.
    const buildWarnings = [...(answer.warnings || [])];
    if (answer.tables?.error) buildWarnings.push(`The decks were marked built, but their availability tables could not be updated: ${answer.tables.error}`);
    const kept = { ...data, completion: updated.completion, buildWarnings, tableRefreshError: !!answer.tables?.error,
      decks: data.decks.map(deck => {
        const saved = updated.decks.find(d => d.id === deck.id);
        return { ...deck, ...(saved ? { completion: saved.completion, standins: saved.standins,
          kit: saved.kit, sleeves: saved.sleeves, sleeves_need: saved.sleeves_need,
          build_scope: saved.build_scope, remaining_intent: saved.remaining_intent } : {}) };
      }) };
    view.buildKit = {};
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

/** All participants contribute copies; optional kit/token steps keep their own unit. */
function packProgress(view) {
  packChooserSync(view);
  if (!view.bar) return;
  packBulkProgress(view);
  const ticks = view.ticks || [];
  packUpdateBar(view, ticks, ticks.filter(t => t.tile), ticks.filter(t => !t.tile));
  const clearButton = view.bar.node.querySelector(".pack-clear");
  if (clearButton) clearButton.disabled = Boolean(view.saving) || !ticks.some(t => t.done);
}

/** "Zombie / Zombie Knight ×8 (Zombie side only, can be sleeved)": a token card and the face this deck
 * uses, and with faces (tokFacesUsed of the deck's needs) whether it needs the other side too:
 * "(Zombie side; both sides used)". */
function assemblyTokenCard(card, faces = null) {
  const face = card.side === "back" ? card.back : card.front;
  const sides = tokSides(card, faces);
  const side = !card.back || !face ? ""
    : sides === "both sides used" ? ` (${face} side; both sides used)` : sides ? ` (${sides})` : ` (${face} side)`;
  return `${card.back ? `${card.front} / ${card.back}` : card.front} ×${card.quantity}${side}`;
}

/** A deck's token lines: a tick to grab the cards for each kind it makes (or a stand-in, said to the
 * opponent), and a line, never ticked, for a kind with no card or still on the way. Nothing is reserved: two
 * decks may want the same card (assemblySharedTokens). tokens: the deck's deck_tokens result, or null when it
 * couldn't be worked out. */
function assemblyTokenTasks(tokens, rows = []) {
  if (!tokens) return null;
  if (tokens.unavailable || tokens.error) return [el("li", { class: "assembly-pending", text: tokens.unavailable || tokens.error })];
  const lines = [];
  const identity = card => {
    const row = rows?.[card.row] || card;
    return [card.side, ...["front", "back", "set", "front_collector_number", "back_collector_number",
      "finish", "quantity", "front_details", "back_details"].map(key => row[key] ?? "")];
  };
  const faces = tokFacesUsed(tokens.needs);
  for (const need of tokens.needs || []) {
    const cards = need.cards || [], standIns = need.stand_ins || [];
    if ((need.state === "ready" || need.state === "check") && cards.length) {
      lines.push(assemblyTick(`Grab ${cards.map((card) => assemblyTokenCard(card, faces)).join(" or ")} for ${need.name}`
        + (need.state === "check" ? " (details not recorded)" : ""), 1,
        need.packing_key || cards.map(identity), `token|${need.key || need.name}`));
    } else if (need.state === "differs" && standIns.length) {
      const card = standIns[0];
      lines.push(assemblyTick(`Stand-in for ${need.name}: ${card.back ? `${card.front} / ${card.back}` : card.front} ×${card.quantity}`
        + ` (${card.why && card.why.length ? `${card.why[0]}; ` : ""}${tokSides(card, faces) ? `${tokSides(card, faces)}; ` : ""}tell your opponent)`, 1,
        need.packing_key || identity(card), `token|${need.key || need.name}`));
    } else if (need.state === "incoming") {
      lines.push(el("li", { class: "assembly-pending", text: `No ${need.name} token yet: ${need.on_the_way || 0} on the way` }));
    } else {
      lines.push(el("li", { class: "assembly-pending", text: `No ${need.name} token: use a stand-in (a spare token card or a die)` }));
    }
  }
  const others = [...(tokens.copies || []), ...(tokens.unlisted || [])];
  if (others.length) {
    lines.push(el("li", { class: "assembly-pending",
      text: `Check by hand: ${others.join(", ")} may make copies or tokens Scryfall doesn't link` }));
  }
  return lines;
}

/** "Shared tokens": the token cards two or more of these decks want (token_plan), hidden when there are
 * none. One card shows one face at a time; nothing is shared out or reserved. */
function assemblySharedTokens(data) {
  const plan = data.token_plan || [];
  if (!plan.length) return null;
  return el("section", { class: "panel pack-extra assembly-tokens" }, el("h2", { text: "Shared tokens" }),
    data.token_plan_note ? el("p", { text: data.token_plan_note }) : null,
    el("ul", { class: "pack-plain" }, plan.map((item) => el("li", {},
      el("b", { text: `${item.back ? `${item.front} / ${item.back}` : item.front} ×${item.quantity}` }), ": ",
      (item.wanted_by || []).map((w, i) => {
        const face = w.side === "back" ? item.back : item.front;
        return `${i ? "; " : ""}${w.token} for ${w.title}${item.back && face ? ` (${face} side)` : ""}`;
      })))));
}
