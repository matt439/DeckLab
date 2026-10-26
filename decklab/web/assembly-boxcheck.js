/* Local counts over the saved physical assembly; only a historical date is persisted. */
"use strict";

const BOX_CHECK_SECTIONS = ["Commander", "Companion", "Deck", "Sideboard"];

function packBoxCheckEvidence(deck) {
  const meta = deck.box_check, physical = packTakeApartContents(deck.take_apart);
  const hash = value => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
  if (!meta || !physical || typeof meta.editable !== "boolean" || !hash(meta.expect) || !hash(meta.recipe_sha256)
      || meta.expect !== physical.sha256 || !(meta.checked_on === null || boxCheckDate(meta.checked_on))
      || !(meta.why_not === null || typeof meta.why_not === "string")) return null;
  for (const rows of Object.values(physical.sections)) {
    const identities = new Set();
    for (const row of rows) {
      const key = JSON.stringify([row.kind, row.name, row.for]);
      if (row.quantity > 9999 || identities.has(key)) return null;
      identities.add(key);
    }
  }
  return { meta, physical };
}

function packBoxCheckButton(view, deck) {
  if (!deck.box_check || deck.completion?.status !== "built" || !/^(casual|commander)\/[^/]+$/.test(deck.id)
      || ownSpace() !== HOME_SPACE || !seesHomeInventory(state.may)) return null;
  const data = view.data, recipe = JSON.stringify(view.selected.map(packSelectedChoice));
  const button = el("button", { type: "button", class: "btn btn-quiet pack-box-check", text: "Check box",
    "aria-label": deck.title + ": check box", onclick: () => {
      if (!assemblyActive(view) || view.hash !== location.hash || view.data !== data || !data.decks.includes(deck)
          || !button.isConnected || !view.results.contains(button) || view.previewing || view.reviewing || view.saving
          || view.boxCheckRefresh?.data === data || document.querySelector("dialog[open]")
          || recipe !== JSON.stringify(view.selected.map(packSelectedChoice))) return;
      const progress = view.progress;
      if (!progress?.loaded || progress.busy || progress.pending.size || progress.error) {
        view.message.textContent = "Save or check the shared packing ticks before opening a box check."; return;
      }
      packReviewBoxCheck(view, deck);
    } });
  return button;
}

function packBoxRowWords(row) {
  return (row.name || "Unspecified stand-in") + (row.kind === "marker" ? " (marked for " + row.for + ")" : "");
}

/** Each deficit/excess belongs to its original physical row; explicit extras never net against it. */
function packBoxDifferences(expected, rows, extras) {
  const missing = [], extra = [];
  for (let index = 0; index < expected.length; index++) {
    const { section, physical } = expected[index], difference = rows[index].quantity - physical.quantity;
    if (difference) (difference < 0 ? missing : extra).push({ section, kind: physical.kind, name: physical.name,
      for: physical.for, quantity: Math.abs(difference) });
  }
  for (const row of extras) extra.push({ section: row.section, kind: "card", name: row.name, for: null, quantity: row.quantity });
  return { missing, extra, expected_cards: expected.reduce((sum, row) => sum + row.physical.quantity, 0),
    found_cards: rows.reduce((sum, row) => sum + row.quantity, 0) + extras.reduce((sum, row) => sum + row.quantity, 0) };
}

function packBoxReceipt(answer, deck, evidence, review) {
  const encode = rows => {
    if (!Array.isArray(rows) || rows.some(row => !row || Object.keys(row).sort().join(",") !== "for,kind,name,quantity,section")) return null;
    return rows.map(row => JSON.stringify([row.section, row.kind, row.name, row.for, row.quantity])).sort().join("\n");
  };
  return answer && typeof answer.saved === "boolean" && answer.id === deck.id && Number.isSafeInteger(answer.revision)
    && answer.revision >= 0 && typeof answer.sha256 === "string" && /^[a-f0-9]{64}$/.test(answer.sha256)
    && (answer.saved ? answer.sha256 !== evidence.meta.expect : answer.sha256 === evidence.meta.expect)
    && (answer.saved ? answer.checked_on !== evidence.meta.checked_on : answer.checked_on === evidence.meta.checked_on)
    && answer.recipe_sha256 === evidence.meta.recipe_sha256 && boxCheckDate(answer.checked_on) !== null
    && answer.expected_cards === review.expected_cards && answer.found_cards === review.found_cards
    && encode(answer.missing) !== null && encode(answer.missing) === encode(review.missing)
    && encode(answer.extra) !== null && encode(answer.extra) === encode(review.extra);
}

function packReviewBoxCheck(view, deck) {
  const evidence = packBoxCheckEvidence(deck), recipe = JSON.stringify(view.selected.map(packSelectedChoice));
  const data = view.data, root = view.root, seq = view.seq, original = JSON.stringify([deck.box_check, deck.take_apart]);
  const expected = [], extras = [], controls = [], acceptedValues = new WeakMap();
  let stage = "edit", pending = false, saved = false, needsRefresh = false, refreshed = false, review = null;
  view.reviewing = true; packProgress(view);
  const ctx = openAssemblySheet(view, "Check " + deck.title + " box", { onClose: () => {
    if (!owner()) return;
    if (saved || needsRefresh) afterClose();
    else if (!pending) { view.reviewing = false; packProgress(view); }
  } });
  const owner = () => assemblyActive(view) && ctx.token === routeToken && ctx.profile === state.profile?.id
    && view.hash === location.hash && view.root === root && view.data === data && view.seq === seq && data.decks.includes(deck)
    && recipe === JSON.stringify(view.selected.map(packSelectedChoice)) && ownSpace() === HOME_SPACE && seesHomeInventory(state.may)
    && original === JSON.stringify([deck.box_check, deck.take_apart]);
  const current = () => owner() && assemblySheetHere(ctx);
  const here = () => current() && [...document.querySelectorAll("dialog[open]")].at(-1) === ctx.sheet.dialog;
  const actionable = (event, part = ctx.sheet.body) => here() && !pending && !saved && !needsRefresh
    && event?.currentTarget?.isConnected && part.contains(event.currentTarget);
  const error = el("p", { class: "form-error", role: "alert", tabindex: "-1" });
  const editing = el("div"), reviewing = el("div", { hidden: true });
  ctx.sheet.body.append(el("p", { text: "Review the recorded physical cards and installed stand-in markers in every section. Count the cards actually in the box, then review any differences." }),
    el("p", { class: "sub", text: "Pictures are representative name-only art. They do not confirm a printing, finish or physical quantity. Saving records a historical date; the counts and differences stay only in this review." }),
    el("p", { class: "sub", text: "Every count starts unreviewed. Tick a tile to fill its full recorded quantity, or enter a whole count. Use 0 when none were found." }), editing, reviewing, error);
  function local(input, valid = () => true) {
    acceptedValues.set(input, input.value);
    const changed = () => {
      if (!here() || stage !== "edit" || pending || saved || needsRefresh || !input.isConnected || !editing.contains(input) || !valid()) input.value = acceptedValues.get(input);
      else if (input.value !== acceptedValues.get(input)) {
        // A native blur can emit change after input already accepted this value. Keep the
        // footer stable so that focusing Review does not replace its pending click target.
        acceptedValues.set(input, input.value); error.textContent = ""; syncTicks(); actions();
      }
    };
    input.addEventListener("input", changed); input.addEventListener("change", changed); controls.push(input); return input;
  }
  const quantity = (input, minimum) => /^\d+$/.test(input.value.trim()) && Number.isSafeInteger(Number(input.value))
    && Number(input.value) >= minimum && Number(input.value) <= 9999 ? Number(input.value) : null;
  function snapshot() {
    const rows = [];
    for (const row of expected) {
      const found = quantity(row.input, 0);
      if (found === null || !row.input.isConnected || !editing.contains(row.input)) return null;
      rows.push({ section: row.section, row: row.index, quantity: found });
    }
    const extraRows = [], seen = new Set();
    for (const row of extras) {
      const name = row.name.value, found = quantity(row.input, 1), section = row.section.value;
      const key = JSON.stringify([section, name]);
      if (found === null || !name || name !== name.trim() || /[\u0000-\u001f\u007f]/.test(name)
          || !BOX_CHECK_SECTIONS.includes(section) || seen.has(key)
          || [row.name, row.input, row.section].some(input => !input.isConnected || !editing.contains(input))) return null;
      seen.add(key); extraRows.push({ section, name, quantity: found });
    }
    return { rows, extras: extraRows, ...packBoxDifferences(expected, rows, extraRows) };
  }
  function syncTicks() {
    for (const row of expected) {
      row.tick.checked = quantity(row.input, 0) === row.physical.quantity;
      acceptedValues.set(row.tick, row.tick.checked);
    }
  }
  function lock() {
    for (const control of controls) control.disabled = pending || saved || needsRefresh || stage !== "edit";
    for (const row of expected) row.tick.disabled = pending || saved || needsRefresh || stage !== "edit";
  }
  function differences() {
    clear(reviewing).append(el("h3", { text: "Review differences" }),
      el("p", { text: plural(review.expected_cards, "recorded physical card") + "; " + plural(review.found_cards, "card") + " found, including extras." }),
      el("p", { class: "sub", text: "Saving the check date keeps the deck's lists, collection, kit and reservations as recorded." }));
    for (const [key, label] of [["missing", "Missing"], ["extra", "Extra"]]) reviewing.append(el("section", {},
      el("h4", { text: label }), review[key].length ? el("ul", {}, review[key].map(row => el("li", {
        text: row.section + ": " + row.quantity + " x " + packBoxRowWords(row) }))) : el("p", { text: "None recorded in this review." })));
    if (!evidence.meta.editable) reviewing.append(el("p", { class: "sub", text: evidence.meta.why_not || "You cannot save a check date for this deck." }));
  }
  function actions() {
    lock();
    sheetActions(ctx.sheet, [saved ? { text: "Done", kind: "primary", onclick: event => { if (here() && event.currentTarget.isConnected) ctx.sheet.close(); } }
      : needsRefresh ? { text: "Reload plan", kind: "primary", onclick: event => {
        if (here() && !pending && event.currentTarget.isConnected) ctx.sheet.close();
      } } : evidence && stage === "review" ? { text: pending ? "Saving check date." : "Save check date", kind: "primary",
        disabled: pending || !evidence.meta.editable, onclick: save }
        : evidence ? { text: "Review differences", kind: "primary", disabled: pending || !snapshot(), onclick: event => {
          if (!actionable(event, ctx.sheet.foot) || stage !== "edit") return;
          review = snapshot(); if (!review) return;
          stage = "review"; editing.hidden = true; reviewing.hidden = false; differences(); error.textContent = ""; actions();
        } } : null,
      !saved && !needsRefresh && stage === "review" ? { text: "Back to counts", disabled: pending, onclick: event => {
        if (!actionable(event, ctx.sheet.foot)) return;
        stage = "edit"; editing.hidden = false; reviewing.hidden = true; error.textContent = ""; actions();
      } } : null,
      !saved ? { text: evidence ? "Cancel" : "Close", disabled: pending, onclick: () => ctx.sheet.close() } : null]);
  }
  function addExtra(event) {
    if (!actionable(event) || stage !== "edit" || extras.length >= 200) return;
    const row = {}, alive = () => extras.includes(row);
    row.section = local(el("select", { "aria-label": "Extra card section" }, BOX_CHECK_SECTIONS.map(section => el("option", { value: section, text: section }))), alive);
    row.section.value = "Deck";
    acceptedValues.set(row.section, "Deck");
    row.name = local(el("input", { type: "text", maxlength: 200, autocomplete: "off", "aria-label": "Extra card exact canonical name" }), alive);
    row.input = local(el("input", { type: "number", inputmode: "numeric", min: 1, max: 9999, step: 1, "aria-label": "Extra physical quantity" }), alive);
    row.node = el("div", { class: "panel" }, el("label", { class: "field" }, el("span", { text: "Section" }), row.section),
      el("label", { class: "field" }, el("span", { text: "Exact canonical card name" }), row.name),
      el("label", { class: "field" }, el("span", { text: "Physical quantity" }), row.input),
      el("button", { type: "button", class: "btn btn-quiet", text: "Remove extra", onclick: event => {
        if (!actionable(event) || stage !== "edit" || !alive()) return;
        extras.splice(extras.indexOf(row), 1); row.node.remove(); actions();
      } }));
    extras.push(row); extraFields.append(row.node); actions(); row.name.focus();
  }
  let extraFields;
  if (!evidence) editing.append(el("p", { class: "box box-warn", text: deck.take_apart?.reason || "The recorded physical contents cannot be checked. Reload the plan before starting a box check." }));
  else {
    if (evidence.meta.checked_on) editing.append(boxCheckDateNote({ box_checked_on: evidence.meta.checked_on }));
    for (const section of BOX_CHECK_SECTIONS) {
      const rows = evidence.physical.sections[section]; if (!rows?.length) continue;
      const tiles = el("div", { class: "card-tiles" }); editing.append(el("section", {}, el("h3", { text: section }), tiles));
      rows.forEach((physical, index) => {
        const row = { section, index, physical };
        row.input = local(el("input", { type: "number", inputmode: "numeric", min: 0, max: 9999, step: 1, value: "",
          "aria-label": section + ": found physical quantity for " + packBoxRowWords(physical), placeholder: "Unreviewed" }));
        row.tick = el("input", { type: "checkbox", "aria-label": section + ": all " + physical.quantity + " " + packBoxRowWords(physical) + " found",
          onchange: () => {
            if (!here() || stage !== "edit" || pending || saved || needsRefresh || !row.tick.isConnected || !editing.contains(row.tick)) {
              row.tick.checked = acceptedValues.get(row.tick); return;
            }
            row.tick.checked = Boolean(row.tick.checked); row.input.value = row.tick.checked ? String(physical.quantity) : "";
            acceptedValues.set(row.tick, row.tick.checked); acceptedValues.set(row.input, row.input.value);
            actions();
          } });
        acceptedValues.set(row.tick, false);
        const art = physical.name && data.box_check_cards?.[physical.name];
        const card = art && art.name === physical.name ? art : null;
        tiles.append(el("div", {}, cardTile(card, { name: packBoxRowWords(physical), qty: physical.quantity, check: row.tick,
          meta: physical.name ? "Representative art; printing and finish unconfirmed" : "Unspecified physical stand-in" }),
          el("label", { class: "field" }, el("span", { text: "Found (0 means reviewed and missing)" }), row.input)));
        expected.push(row);
      });
    }
    extraFields = el("div");
    editing.append(el("section", {}, el("h3", { text: "Extra cards found" }),
      el("p", { class: "sub", text: "Use the exact canonical card name; the server checks it before saving. Extras stay separate from missing recorded rows." }),
      extraFields, el("button", { type: "button", class: "btn", text: "Add extra card", onclick: addExtra })));
    if (!evidence.meta.editable) editing.append(el("p", { class: "sub", text: evidence.meta.why_not || "You cannot save a check date for this deck." }));
  }
  function afterClose() {
    if (pending || refreshed || !owner()) return;
    if (!saved && !needsRefresh) { view.reviewing = false; packProgress(view); return; }
    view.boxCheckRefresh = { data };
    const entry = ctx.sheet.entry;
    const stop = () => { window.removeEventListener("popstate", landed); window.removeEventListener("hashchange", stop); };
    const landed = () => {
      stop();
      if (refreshed || !owner() || entry && (history.state?.sheet === entry.token || history.state?.pos !== entry.pos - 1)) return;
      refreshed = true; view.reviewing = false; view.boxCheckRefresh = null; clearTimeout(view.timer); view.run();
    };
    if (!entry || entry.fromHistory || history.state?.sheet !== entry.token) landed();
    else { window.addEventListener("popstate", landed); window.addEventListener("hashchange", stop); }
  }
  async function save(event) {
    if (!actionable(event, ctx.sheet.foot) || stage !== "review" || !evidence.meta.editable || !review
        || JSON.stringify(snapshot()) !== JSON.stringify(review)) return;
    const trigger = document.activeElement;
    const focusOwned = () => document.activeElement === trigger || document.activeElement === document.body || !document.activeElement?.isConnected;
    pending = true; error.textContent = ""; packSaving(view, true); actions();
    try {
      const answer = await apiWrite("/api/deck/box-check", { id: deck.id, expect: evidence.meta.expect,
        recipe_sha256: evidence.meta.recipe_sha256, rows: review.rows, extras: review.extras });
      state.library = null;
      if (!packBoxReceipt(answer, deck, evidence, review)) throw new Error("The box check result could not be confirmed.");
      if (!owner()) return;
      saved = true; stage = "saved"; view.boxCheckRefresh = { data };
      if (current()) {
        const confirmation = el("p", { role: "status", tabindex: "-1", text: "Last box check recorded: " + answer.checked_on
          + ". Contents may have changed since. Only the date was saved; keep this difference review until you are done." });
        reviewing.append(confirmation); actions(); if (here() && focusOwned()) confirmation.focus();
      }
    } catch (failure) {
      state.library = null;
      if (!owner()) return;
      if (failure.status === 400 && current()) {
        stage = "edit"; editing.hidden = false; reviewing.hidden = true;
        error.textContent = failure.message + " Review the corrected counts and exact card names before saving again.";
      } else {
        needsRefresh = true; view.boxCheckRefresh = { data };
        error.textContent = (failure.status ? failure.message : "The box check result could not be confirmed.") + " Reload the plan before saving again.";
      }
      if (here() && focusOwned()) error.focus();
    } finally {
      pending = false;
      if (owner()) {
        packSaving(view, false); if (current()) actions();
        else if (ctx.sheet.closed) afterClose();
      }
    }
  }
  actions();
  return ctx;
}
