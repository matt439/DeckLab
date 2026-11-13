/* The Collection page's "Storage setup…" (E8-S25 slice 4, decklab/design/storage-setting.md 2.6): a
 * space's own people say where its loose cards are kept. One row per container (name, kind, capacity,
 * sections one per line or "4 rows", order, sleeved; Add, Remove, Move up and down) and which container
 * cards with no location go to. Preview (POST /api/storage/preview, which writes nothing) shows the
 * counts per container now and after, how many recorded locations would move between containers (by
 * count, never naming a row) and the new location suggestions; Save (PUT /api/storage) sends the
 * revision the sheet read, and a setup saved meanwhile is a 409 offering the latest. Before migration
 * 0028 the sheet says the database needs updating and saves nothing. Shared with collection.js
 * (openStorageSetup) and storage-locations.js (the count line's Change…). */
"use strict";

const STORAGE_KIND_WORDS = { box: "Box", binder: "Binder", shelf: "Shelf", other: "Other" };
const STORAGE_ORDER_WORDS = { "colour-type": "By colour, then type", set: "By set and number", name: "By name", none: "No particular order" };
const STORAGE_ROWS = /^\s*(\d{1,2})\s+rows?\s*$/i;

/** Open the sheet for the space's own people. Resolves with its context, or null. */
async function openStorageSetup(cv) {
  if (!colActive(cv) || cv.busy || !cv.editable) return null;
  const sheet = colOpenSheet(`Storage setup for ${colWhose(cv.space)}`, { wide: true });
  const ctx = { cv, sheet, busy: false, review: null, keys: 0, profile: state.profile && state.profile.id };
  ctx.here = () => !sheet.closed && colActive(cv) && ctx.profile === (state.profile && state.profile.id);
  ctx.message = el("div", { class: "col-sheet-message", role: "status", "aria-live": "polite" });
  ctx.edit = el("div", { class: "col-form storage-setup" });
  ctx.reviewBox = el("div", { class: "storage-review", hidden: true });
  sheet.body.append(ctx.message, ctx.edit, ctx.reviewBox);
  ctx.edit.append(loadingBox("Loading the storage setup…", { small: true }));
  sheetActions(sheet, [{ text: "Cancel", value: "cancel", onclick: () => sheet.close() }]);
  try {
    const data = await api(`/api/storage?space=${encodeURIComponent(cv.space)}`);
    if (!ctx.here()) return null;
    storageTake(ctx, data);
  } catch (error) {
    if (!ctx.here()) return null;
    clear(ctx.edit);
    storageSay(ctx, "crit", `The storage setup couldn't be loaded: ${error.message}`);
  }
  return ctx;
}

function storageSay(ctx, kind, ...paragraphs) {
  clear(ctx.message);
  if (!paragraphs.length) return;
  ctx.message.append(el("div", { class: `box box-${kind}`, role: kind === "info" ? null : "alert" },
    paragraphs.map((text) => el("p", { text }))));
}

/** A GET /api/storage answer (or a 409's latest) into the sheet's draft, then the editing step. */
function storageTake(ctx, data) {
  ctx.data = data;
  ctx.revision = Number.isSafeInteger(data.revision) ? data.revision : 0;
  const record = data.storage || { default: null, containers: [] };
  ctx.containers = (record.containers || []).map((c) => storageDraft(ctx, c));
  const first = ctx.containers.find((c) => c.id && c.id === record.default);
  ctx.defaultKey = first ? first.key : "";
  if (!data.ready) {
    clear(ctx.edit);
    storageSay(ctx, "warn", "The storage setup can't be changed yet: Deck Lab's database needs updating on the PC.");
    sheetActions(ctx.sheet, [{ text: "Close", value: "cancel", onclick: () => ctx.sheet.close() }]);
    return;
  }
  if (!data.can_edit) {
    clear(ctx.edit);
    storageSay(ctx, "info", "Only this collection's own people can change its storage setup.");
    sheetActions(ctx.sheet, [{ text: "Close", value: "cancel", onclick: () => ctx.sheet.close() }]);
    return;
  }
  showStorageEdit(ctx);
}

function storageDraft(ctx, c = {}) {
  return { key: `c${++ctx.keys}`, id: c.id || "", name: c.name || "", kind: c.kind || "box",
    capacity: c.capacity == null ? "" : String(c.capacity), sections: (c.sections || []).join("\n"),
    order: c.order || "none", sleeved: c.sleeved === true,
    holds: c.holds && typeof c.holds === "object" && !Array.isArray(c.holds) ? { ...c.holds } : {} };
}

/** Slice 7: what each section of a colour-type container holds ({section: group}), as chosen beside its sections. */
const STORAGE_HOLDS_WORDS = { "": "Any cards", creatures: "Creatures", spells: "Spells", lands: "Lands", tokens: "Token cards" };

/** The "What each section holds" choices, for a colour-type container with sections; empty otherwise. */
function storageHoldsBox(ctx, c, k, box) {
  clear(box);
  const sections = storageSections(c.sections);
  box.hidden = c.order !== "colour-type" || !sections.length;
  if (box.hidden) return box;
  const label = c.name.trim() || "this container";
  add(box, [el("legend", { text: "What each section holds" }),
    el("small", { class: "field-hint", text: `Where these go and Build decks then say each card's section, such as “${sections[0]} · Creatures”.` }),
    sections.slice(0, 50).map((section, n) => {
      const select = el("select", { id: k(`holds-${n}`), "aria-label": `What ${section} of ${label} holds`,
        onchange: (e) => { c.holds[section] = e.target.value; } },
      Object.entries(STORAGE_HOLDS_WORDS).map(([value, text]) => el("option", { value, text, selected: (c.holds[section] || "") === value || null })));
      return el("label", { class: "field storage-holds-row", for: select.id }, el("span", { text: section }), select);
    })]);
  return box;
}

/** A container's holds for the record: its current sections' chosen groups (colour-type only), or an Error. */
function storageHolds(c, name, sections) {
  if (c.order !== "colour-type") return {};
  const out = {}, used = new Set();
  for (const section of sections) {
    const group = c.holds[section] || "";
    if (!group) continue;
    if (used.has(group)) throw new Error(`${name} has two sections holding ${STORAGE_HOLDS_WORDS[group].toLowerCase()}. Choose one.`);
    used.add(group);
    out[section] = group;
  }
  return out;
}

function storageLimits(ctx) {
  const limits = (ctx.data && ctx.data.limits) || {};
  return { containers: limits.containers || 20, name: limits.name || 40, capacity: limits.capacity || 100000 };
}

function showStorageEdit(ctx) {
  ctx.review = null;
  ctx.reviewBox.hidden = true;
  ctx.edit.hidden = false;
  drawStorageEdit(ctx);
  sheetActions(ctx.sheet, [{ text: "Cancel", value: "cancel", onclick: () => ctx.sheet.close() },
    { text: "Preview", kind: "primary", value: "preview", onclick: () => previewStorage(ctx) }]);
}

/** The editing step: the intro, one fieldset per container, Add a container and the default choice. */
function drawStorageEdit(ctx) {
  const id = (key) => `storage-${key}-${ctx.sheet.heading.id}`;
  const limits = storageLimits(ctx);
  const home = ctx.cv.space === HOME_SPACE;
  const intro = el("p", { class: "sub", text: "Where this collection's loose cards are kept: a storage box, a binder, a shelf. "
    + "A card's storage location belongs to the container one of whose sections (or its name) it starts with, such as "
    + `${home ? "“Row 2, B”" : "“Binder, page 3”"}. The Card list counts each container's cards.` });
  const list = el("ol", { class: "storage-containers" }, ctx.containers.map((c, i) => storageFieldset(ctx, c, i, id)));
  const adder = el("button", { type: "button", class: "btn btn-secondary", text: "Add a container",
    disabled: ctx.containers.length >= limits.containers || null, onclick: () => {
      ctx.containers.push(storageDraft(ctx, { kind: ctx.containers.length ? "binder" : "box" }));
      if (ctx.containers.length === 1) ctx.defaultKey = ctx.containers[0].key;
      drawStorageEdit(ctx);
      const inputs = ctx.edit.querySelectorAll(".storage-name");
      if (inputs.length) inputs[inputs.length - 1].focus();
    } });
  const select = el("select", { id: id("default"), onchange: (e) => { ctx.defaultKey = e.target.value; } },
    el("option", { value: "", text: "Nowhere in particular" }),
    ctx.containers.map((c) => el("option", { value: c.key, text: c.name.trim() || "(the container with no name yet)", selected: c.key === ctx.defaultKey || null })));
  add(clear(ctx.edit), [intro,
    ctx.containers.length ? list : el("p", { class: "sub", text: home
      ? "No containers: the Card list won't count storage, and the built-in storage box is turned off once this is saved."
      : "No containers yet. Add one to have the Card list count it." }),
    el("div", { class: "actions" }, adder),
    ctx.containers.length ? el("label", { class: "field", for: select.id }, el("span", { text: "Cards with no location go to" }), select,
      el("small", { class: "field-hint", text: "Copies with no storage location recorded are counted there." })) : null]);
}

function storageFieldset(ctx, c, i, id) {
  const k = (key) => id(`${key}-${c.key}`);
  const name = el("input", { id: k("name"), class: "storage-name", type: "text", maxlength: storageLimits(ctx).name, autocomplete: "off",
    value: c.name, placeholder: "Such as Storage box or Binder", oninput: (e) => { c.name = e.target.value; } });
  const kind = el("select", { id: k("kind"), onchange: (e) => { c.kind = e.target.value; } },
    Object.entries(STORAGE_KIND_WORDS).map(([value, text]) => el("option", { value, text, selected: value === c.kind || null })));
  const capacity = el("input", { id: k("capacity"), type: "text", inputmode: "numeric", maxlength: 6, autocomplete: "off",
    value: c.capacity, placeholder: "Not known", oninput: (e) => { c.capacity = e.target.value; } });
  const holds = el("fieldset", { class: "storage-holds" });
  const sections = el("textarea", { id: k("sections"), rows: 3, spellcheck: "false", value: c.sections,
    placeholder: "Row 1\nRow 2", oninput: (e) => { c.sections = e.target.value; }, onchange: () => storageHoldsBox(ctx, c, k, holds) });
  sections.value = c.sections;
  const order = el("select", { id: k("order"), onchange: (e) => { c.order = e.target.value; storageHoldsBox(ctx, c, k, holds); } },
    Object.entries(STORAGE_ORDER_WORDS).map(([value, text]) => el("option", { value, text, selected: value === c.order || null })));
  const sleeved = el("input", { id: k("sleeved"), type: "checkbox", checked: c.sleeved || null,
    onchange: (e) => { c.sleeved = e.target.checked; } });
  const move = (by) => {
    const j = i + by;
    if (j < 0 || j >= ctx.containers.length) return;
    [ctx.containers[i], ctx.containers[j]] = [ctx.containers[j], ctx.containers[i]];
    drawStorageEdit(ctx);
    const row = ctx.edit.querySelector(`[data-storage="${c.key}"]`);
    const again = row && row.querySelector(`[data-move="${by < 0 ? "up" : "down"}"]`);
    if (again && !again.disabled) again.focus();
  };
  const label = c.name.trim() || `Container ${i + 1}`;
  return el("li", { class: "storage-container", "data-storage": c.key },
    el("fieldset", {},
      el("legend", { text: label }),
      el("label", { class: "field", for: name.id }, el("span", { text: "Name" }), name),
      el("div", { class: "storage-pair" },
        el("label", { class: "field", for: kind.id }, el("span", { text: "Kind" }), kind),
        el("label", { class: "field", for: capacity.id }, el("span", { text: "Holds (cards)" }), capacity)),
      el("label", { class: "field", for: sections.id }, el("span", { text: "Sections" }), sections,
        el("small", { class: "field-hint", text: "One per line, or a count such as “4 rows” for Row 1 to Row 4. They're the location suggestions." })),
      el("label", { class: "field", for: order.id }, el("span", { text: "Cards are ordered" }), order),
      storageHoldsBox(ctx, c, k, holds),
      el("label", { class: "choice", for: sleeved.id }, sleeved, el("span", { text: "Its cards are kept sleeved" })),
      el("div", { class: "actions storage-moves" },
        el("button", { type: "button", class: "btn btn-quiet", text: "Move up", "data-move": "up", disabled: i === 0 || null,
          "aria-label": `Move ${label} up`, onclick: () => move(-1) }),
        el("button", { type: "button", class: "btn btn-quiet", text: "Move down", "data-move": "down",
          disabled: i === ctx.containers.length - 1 || null, "aria-label": `Move ${label} down`, onclick: () => move(1) }),
        el("button", { type: "button", class: "btn btn-quiet btn-danger", text: "Remove", "aria-label": `Remove ${label}`, onclick: () => {
          ctx.containers.splice(i, 1);
          if (ctx.defaultKey === c.key) ctx.defaultKey = "";
          drawStorageEdit(ctx);
        } }))));
}

/** "4 rows" as Row 1 to Row 4; otherwise one section per non-blank line. */
function storageSections(text) {
  const rows = STORAGE_ROWS.exec(text);
  if (rows) return Array.from({ length: Math.min(50, Number(rows[1])) }, (_, n) => `Row ${n + 1}`);
  return String(text).split("\n").map((line) => line.replace(/\s+/g, " ").trim()).filter(Boolean);
}

/** The record the draft describes, or an Error naming what to fix first. */
function storageRecord(ctx) {
  const limits = storageLimits(ctx);
  const containers = ctx.containers.map((c, i) => {
    const name = c.name.replace(/\s+/g, " ").trim();
    if (!name) throw new Error(`Container ${i + 1} needs a name.`);
    const capacity = c.capacity.replace(/[\s,]/g, "");
    if (capacity && (!/^\d+$/.test(capacity) || Number(capacity) < 1 || Number(capacity) > limits.capacity)) {
      throw new Error(`${name}'s capacity must be a whole number of cards from 1 to ${num(limits.capacity)}, or blank when you don't know it.`);
    }
    const sections = storageSections(c.sections), holds = storageHolds(c, name, sections);
    return { ...(c.id ? { id: c.id } : {}), name, kind: c.kind, capacity: capacity ? Number(capacity) : null,
      sections, order: c.order, sleeved: c.sleeved, ...(Object.keys(holds).length ? { holds } : {}) };
  });
  const chosen = ctx.containers.find((c) => c.key === ctx.defaultKey);
  const fallback = chosen ? (chosen.id || chosen.name.replace(/\s+/g, " ").trim()) : null;
  return { default: fallback, containers };
}

function storageBusy(ctx, busy) {
  ctx.busy = busy;
  for (const control of ctx.sheet.body.querySelectorAll("button, input, select, textarea")) control.disabled = busy;
  for (const button of ctx.sheet.foot.querySelectorAll("button")) button.disabled = busy;
}

async function previewStorage(ctx) {
  if (ctx.busy || !ctx.here()) return;
  let storage;
  try { storage = storageRecord(ctx); } catch (error) { storageSay(ctx, "warn", error.message); return; }
  storageBusy(ctx, true);
  clear(ctx.message).append(loadingBox("Working out what changes…", { small: true }));
  try {
    const answer = await apiWrite("/api/storage/preview", { space: ctx.cv.space, storage });
    if (!ctx.here()) return;
    storageBusy(ctx, false);
    clear(ctx.message);
    ctx.review = answer;
    drawStorageReview(ctx);
  } catch (error) {
    if (!ctx.here()) return;
    storageBusy(ctx, false);
    if (!ctx.review) drawStorageEdit(ctx);
    storageSay(ctx, "crit", error.message);
  }
}

/** One container's count, as the review lists it: "Binder: about 310 of 360 cards". */
function storageCountLine(c) {
  if (c.cards === null || c.cards === undefined) return c.name;
  return c.capacity ? `${c.name}: about ${num(c.cards)} of ${num(c.capacity)} cards${c.cards > c.capacity ? " (over capacity)" : ""}`
    : `${c.name}: about ${plural(c.cards, "card")}`;
}

function storageCounts(setup) {
  if (!setup || !setup.containers.length) return el("p", { class: "sub", text: "No containers." });
  return el("ul", { class: "storage-counts" }, setup.containers.map((c) => el("li", { text: storageCountLine(c) })),
    setup.elsewhere ? el("li", { class: "sub", text: `Somewhere else: about ${plural(setup.elsewhere, "card")}` }) : null,
    setup.unplaced ? el("li", { class: "sub", text: `No location and nowhere to go: about ${plural(setup.unplaced, "card")}` }) : null);
}

/** The preview: counts now and after, the locations that move (by count), the new suggestions; Back and Save. */
function drawStorageReview(ctx) {
  const answer = ctx.review;
  ctx.edit.hidden = true;
  ctx.reviewBox.hidden = false;
  const where = (name) => name === null ? "somewhere else" : name;
  const moves = answer.moves || [];
  const suggestions = (answer.after && answer.after.suggestions) || answer.storage.containers.flatMap((c) => c.sections.length ? c.sections : [c.name]);
  const fallback = answer.storage.containers.find((c) => c.id === answer.storage.default);
  add(clear(ctx.reviewBox), [
    answer.counts_error ? el("p", { class: "box box-warn", text: answer.counts_error }) : [
      el("h3", { text: "Now" }), storageCounts(answer.now),
      el("h3", { text: "After saving" }), storageCounts(answer.after)],
    el("h3", { text: "Recorded locations" }),
    moves.length ? el("ul", { class: "storage-moves-list" }, moves.map((m) => el("li", {
      text: `${plural(m.locations, "recorded location")} would move from ${where(m.from)} to ${where(m.to)}.` })))
      : el("p", { class: "sub", text: "No recorded location changes container." }),
    el("p", { class: "sub", text: fallback ? `Cards with no location go to ${fallback.name}.` : "Cards with no location aren't counted in any container." }),
    el("h3", { text: "Location suggestions" }),
    el("p", { class: "sub", text: suggestions.length ? suggestions.join(", ") : "None: the card sheet suggests only locations already used." }),
    storageHoldsReview(answer.storage)]);
  sheetActions(ctx.sheet, [{ text: "Back", value: "back", onclick: () => { if (!ctx.busy) { clear(ctx.message); showStorageEdit(ctx); } } },
    { text: "Save storage setup", kind: "primary", value: "save", onclick: () => saveStorage(ctx) }]);
  const heading = ctx.reviewBox.querySelector("h3");
  if (heading) { heading.tabIndex = -1; heading.focus(); }
}

/** The review's "What each section holds" (slice 7): one line per container whose sections hold groups. */
function storageHoldsReview(storage) {
  const lines = (storage.containers || []).filter((c) => c.holds && Object.keys(c.holds).length).map((c) =>
    el("li", { text: `${c.name}: ${Object.entries(c.holds).map(([section, group]) =>
      `${section} holds ${(STORAGE_HOLDS_WORDS[group] || group).toLowerCase()}`).join(", ")}` }));
  return lines.length ? [el("h3", { text: "What each section holds" }), el("ul", { class: "storage-holds-list" }, lines)] : null;
}

async function saveStorage(ctx) {
  const cv = ctx.cv;
  if (ctx.busy || !ctx.here() || !ctx.review) return;
  const answer = ctx.review;
  storageBusy(ctx, true);
  clear(ctx.message).append(loadingBox("Saving the storage setup…", { small: true }));
  try {
    const saved = await apiWrite("/api/storage", { profile: ctx.profile, space: cv.space, expect: ctx.revision, storage: answer.storage }, "PUT");
    if (!ctx.here()) return;
    ctx.sheet.close();
    if (answer.after && !answer.counts_error) {
      const setup = colStorageSetup({ ...answer.after, source: saved.source || "saved" });
      if (setup) cv.storageSetup = setup;
    } else {
      cv.storageSetup = colStorageSetup({ source: "saved", default: saved.storage.default, containers: saved.storage.containers.map((c) =>
        ({ ...c, cards: null })), elsewhere: null, unplaced: null, not_counted: null,
        suggestions: saved.storage.containers.flatMap((c) => c.sections.length ? c.sections : [c.name]) });
    }
    drawColStorageBox(cv);
    colSay(cv, "Storage setup saved.");
  } catch (error) {
    if (!ctx.here()) return;
    storageBusy(ctx, false);
    if (error.status === 409 && error.data && error.data.reason === "migration") {
      storageSay(ctx, "warn", "The storage setup can't be saved yet: Deck Lab's database needs updating on the PC. Nothing was saved.");
      return;
    }
    if (error.status === 409 && error.data && error.data.latest) {
      const latest = error.data.latest;
      storageSay(ctx, "warn", "The storage setup was changed somewhere else while this sheet was open. Nothing was saved.",
        "Load the latest to start again from it (your changes here are discarded), or Back to keep them for now.");
      sheetActions(ctx.sheet, [{ text: "Back", value: "back", onclick: () => { if (!ctx.busy) { clear(ctx.message); showStorageEdit(ctx); } } },
        { text: "Load the latest", kind: "primary", value: "latest", onclick: () => { clear(ctx.message); storageTake(ctx, latest); } }]);
      return;
    }
    storageSay(ctx, "crit", `The storage setup couldn't be saved: ${error.message}`);
  }
}
