/* Packing choices are reviewed here; only the explicit save changes deck metadata. */
"use strict";

const assemblySheets = new Set();

function closeAssemblySheets(closeChooser = true) {
  for (const sheet of [...assemblySheets]) sheet.close();
  if (closeChooser) { closePackingChoosers(); closePackingSwitchers(); }
}

function openAssemblySheet(view, title, options = {}) {
  const sheet = openSheet(title, { ...options, onClose: result => {
    assemblySheets.delete(sheet);
    if (options.onClose) options.onClose(result);
  } });
  assemblySheets.add(sheet);
  return { view, sheet, data: view.data, profile: state.profile?.id, token: routeToken };
}

function assemblySheetHere(ctx) {
  return !ctx.sheet.closed && ctx.profile === state.profile?.id && ctx.token === routeToken
    && assemblyActive(ctx.view) && ctx.view.data === ctx.data;
}

/** Validate the recorded physical checklist, never substitute the displayed intended list. */
function packTakeApartContents(info) {
  if (!info || info.available !== true || !/^[a-f0-9]{64}$/.test(info.sha256 || "")
      || typeof info.can_take_apart !== "boolean" || !["assembled", "built-list"].includes(info.source)
      || !["target", "owned"].includes(info.version)
      || !Number.isSafeInteger(info.card_count) || info.card_count < 1 || info.card_count > 20000
      || !info.sections || typeof info.sections !== "object" || Array.isArray(info.sections)
      || !Array.isArray(info.sections.Deck) || !info.sections.Deck.length
      || Object.keys(info.sections).some(key => !["Commander", "Companion", "Deck", "Sideboard"].includes(key))
      || !Array.isArray(info.tokens) || !Number.isSafeInteger(info.token_count) || info.token_count < 0
      || typeof info.tokens_recorded !== "boolean") return null;
  const named = name => typeof name === "string" && name.trim() && !/[\u0000-\u001f\u007f]/.test(name);
  let cards = 0, rows = 0;
  for (const section of Object.values(info.sections)) {
    if (!Array.isArray(section)) return null;
    for (const row of section) {
      if (!row || !Number.isSafeInteger(row.quantity) || row.quantity < 1
          || !["card", "marker"].includes(row.kind) || !(named(row.name) || row.kind === "marker" && row.name === null)
          || row.kind === "marker" && !named(row.for) || row.kind === "card" && row.for !== null
          || (row.name === null ? row.basic !== null : typeof row.basic !== "boolean")) return null;
      cards += row.quantity; rows++;
    }
  }
  if (rows > 2000 || cards !== info.card_count) return null;
  let tokens = 0;
  for (const row of info.tokens) {
    if (!row || !Number.isSafeInteger(row.quantity) || row.quantity < 1 || !named(row.front)
        || !(row.back == null || row.back === "" || named(row.back))
        || !(row.set == null || typeof row.set === "string") || !(row.number == null || typeof row.number === "string")) return null;
    tokens += row.quantity;
  }
  return tokens === info.token_count && (info.tokens_recorded || !tokens) ? info : null;
}

function packTakeApartButton(view, deck) {
  if (!deck.take_apart || deck.completion?.status !== "built") return null;
  const data = view.data, recipe = JSON.stringify(view.selected.map(packSelectedChoice));
  const button = el("button", { type: "button", class: "btn btn-quiet pack-take-apart", text: "Take-apart checklist",
    "aria-label": `${deck.title}: take-apart checklist`, onclick: () => {
      if (!assemblyActive(view) || view.hash !== location.hash || view.data !== data || !data.decks.includes(deck)
          || !button.isConnected || !view.results.contains(button) || view.previewing || view.reviewing || view.saving
          || document.querySelector("dialog[open]") || recipe !== JSON.stringify(view.selected.map(packSelectedChoice))) return;
      const progress = view.progress;
      if (!progress?.loaded || progress.busy || progress.pending.size || progress.error) {
        view.message.textContent = "Save or check the shared packing ticks before opening the take-apart checklist.";
        return;
      }
      packReviewTakeApart(view, deck);
    } });
  return button;
}

/** These local checks never reserve cards or share packing ticks. The final save changes status once. */
function packReviewTakeApart(view, deck) {
  const info = packTakeApartContents(deck.take_apart), checks = [];
  const recipe = JSON.stringify(view.selected.map(packSelectedChoice));
  view.reviewing = true; packProgress(view);
  let pending = false, saved = false, finished = false, needsRefresh = false;
  const ctx = openAssemblySheet(view, `Take apart ${deck.title}`, { onClose: () => {
    if (owner()) { view.reviewing = false; if (saved) finish(); else packProgress(view); }
  } });
  const owner = () => assemblyActive(view) && view.hash === location.hash && view.data === ctx.data
    && recipe === JSON.stringify(view.selected.map(packSelectedChoice));
  const currentSheet = () => owner() && assemblySheetHere(ctx);
  const here = () => currentSheet() && [...document.querySelectorAll("dialog[open]")].at(-1) === ctx.sheet.dialog;
  const error = el("p", { class: "form-error", role: "alert", tabindex: "-1" });
  const fields = el("div");
  const addCheck = (parent, text) => {
    let accepted = false;
    const input = el("input", { type: "checkbox", onchange: () => {
      if (!here() || pending || saved) { input.checked = accepted; return; }
      accepted = Boolean(input.checked);
      actions();
    } });
    checks.push(input); parent.append(el("label", { class: "choice" }, input, el("span", { text })));
  };
  ctx.sheet.body.append(el("p", { text: "Unsleeve the recorded physical cards and return them to storage. Check the box before recording that this deck is taken apart. Its intended lists stay saved." }));
  if (!info) {
    ctx.sheet.body.append(el("p", { class: "box box-warn", text: deck.take_apart.reason || "The recorded physical contents cannot be checked. Refresh the plan or repair the deck record first." }));
  } else {
    ctx.sheet.body.append(el("p", { class: "sub", text: `${plural(info.card_count, "physical card")}. These are recorded card names, not confirmed printing assignments.` }), fields);
    for (const section of ["Commander", "Companion", "Deck", "Sideboard"]) {
      const rows = info.sections[section];
      if (!rows?.length) continue;
      const part = el("section", {}, el("h3", { text: section })); fields.append(part);
      for (const row of rows) addCheck(part, row.kind === "marker"
        ? `${row.quantity} x ${row.name || "spare card"} (marked for ${row.for})`
        : `${row.quantity} x ${row.name}`);
    }
    const tokens = el("section", {}, el("h3", { text: "Token cards" })); fields.append(tokens);
    for (const row of info.tokens) addCheck(tokens, `Return ${row.quantity} x ${row.front}${row.back ? ` // ${row.back}` : ""}`
      + `${row.set ? ` (${String(row.set).toUpperCase()}${row.number ? ` ${row.number}` : ""})` : ""} to the token pile`);
    addCheck(tokens, info.tokens_recorded ? "Check the box for any other token or reminder cards"
      : "Check for token or reminder cards and return any to the token pile; none are recorded as packed");
    const kit = el("section", {}, el("h3", { text: "Sleeves and deck box" })); fields.append(kit);
    if (info.kit_reason) kit.append(el("p", { class: "sub", text: info.kit_reason }));
    for (const [key, title] of [["sleeves", "Sleeves"], ["deck_box", "Deck box"]]) {
      const ref = info.kit?.[key];
      const label = ref && ["linked", "text"].includes(ref.state) ? assemblyKitName(ref) : null;
      addCheck(kit, `Put away ${title.toLowerCase()}${label ? `: ${label}` : ref ? " (recorded accessory needs checking)"
        : info.kit ? " (not recorded)" : " (details not visible)"}`);
    }
    if (!info.can_take_apart) ctx.sheet.body.append(el("p", { class: "sub", text: info.why_not || "You cannot change this deck." }));
  }
  ctx.sheet.body.append(error);
  function actions() {
    sheetActions(ctx.sheet, [saved ? { text: "Done", kind: "primary", onclick: () => finish() }
      : needsRefresh ? { text: "Refresh plan", kind: "primary", onclick: () => {
        if (!here() || pending) return;
        ctx.sheet.close(); view.reviewing = false; packChanged(view); clearTimeout(view.timer); view.run();
      } } : info ? { text: "Mark deck taken apart", kind: "primary", disabled: pending || !info.can_take_apart || checks.some(input => !input.checked), onclick: save } : null,
      !saved ? { text: info ? "Cancel" : "Close", disabled: pending, onclick: () => ctx.sheet.close() } : null]);
  }
  function finish() {
    if (!owner() || !saved || finished || !ctx.sheet.closed && !here()) return;
    finished = true;
    ctx.sheet.close(); view.reviewing = false;
    view.selected = view.selected.filter(item => item.id !== deck.id);
    view.choices = view.choices.map(choice => choice.id === deck.id ? { ...choice, status: "building" } : choice);
    view.sideboardChoosing?.delete(deck.id);
    if (view.buildKit) delete view.buildKit[deck.id];
    packChanged(view); clearTimeout(view.timer); view.run();
    showToast(`${deck.title} is now marked as taken apart.`);
  }
  async function save() {
    if (!here() || !info || !info.can_take_apart || pending || saved || needsRefresh || checks.some(input => !input.checked)) return;
    const trigger = document.activeElement;
    const focusOwned = () => [document.body, trigger].includes(document.activeElement) || !document.activeElement?.isConnected;
    pending = true; checks.forEach(input => { input.disabled = true; }); error.textContent = "";
    packSaving(view, true); actions();
    try {
      const answer = await apiWrite("/api/deck/save", { id: deck.id, sha256: info.sha256, fields: { status: "building" } });
      if (answer.saved !== true || answer.id !== deck.id) throw new Error("The save result could not be confirmed.");
      state.library = null;
      if (!owner()) return;
      saved = true; packSaving(view, false);
      if (!currentSheet()) { finish(); return; }
      const confirmation = el("p", { role: "status", tabindex: "-1", text: `${deck.title} is marked as taken apart. Its recorded cards, tokens, sleeves and box are free again. Its intended lists are kept.` });
      clear(ctx.sheet.body).append(confirmation);
      if (answer.stale_tables?.length) ctx.sheet.body.append(tablesLaterNote("Some availability tables need updating."));
      actions();
      if (here() && focusOwned()) confirmation.focus();
    } catch (failure) {
      state.library = null; // A lost response may follow a committed save; the next read must be fresh.
      if (!owner()) return;
      packSaving(view, false); needsRefresh = true;
      if (!currentSheet()) { view.reviewing = false; view.run(); return; }
      error.textContent = failure.status ? `${failure.message} Refresh the plan before trying again.`
        : "The save result could not be confirmed. Refresh the plan before trying again.";
      if (here() && focusOwned()) error.focus();
    } finally {
      pending = false;
      if (owner()) { packSaving(view, false); if (currentSheet()) actions(); }
    }
  }
  actions();
  return ctx;
}

/** Choose kit now, then save it with the status, built list and physical stand-ins. */
function packReviewBuilt(view) {
  return new Promise(resolve => {
    const ctx = openAssemblySheet(view, "Finish building", { onClose: result => resolve(result || null) });
    const decks = ctx.data.completion.decks;
    const forms = [], draft = view.buildKit || (view.buildKit = {});
    const error = el("p", { class: "form-error", role: "alert" });
    let items = [], loading = decks.some(deck => deck.kit?.editable), failed = false;
    const fields = el("div", {});
    ctx.sheet.body.append(el("p", { text: "Confirm the list you put together and choose its sleeves and deck box. They are saved together." }), fields, error);
    function actions() {
      sheetActions(ctx.sheet, [
        failed ? { text: "Try again", onclick: load } : null,
        { text: decks.length === 1 ? "Mark as built" : `Mark ${decks.length} decks built`, kind: "primary",
          disabled: loading || failed || !!boxProblem(), onclick: async () => {
            if (!assemblySheetHere(ctx) || loading || failed || boxProblem()) return;
            const kit = Object.fromEntries(forms.map(form => [form.id, Object.fromEntries(
              Object.entries(form.inputs).map(([field, input]) => [field, input.value || null]))]));
            // Sleeves another deck already has (or another deck here gets too) are warned about first
            // (E8-S20, 2026-10-19); sharing a design is allowed, so it asks rather than refuses.
            const shared = sharedSleeves(kit);
            if (shared.length) {
              const choice = await askAccessoryChoice(shared.length === 1 ? `Use ${shared[0].label} for ${shared[0].deck} too?`
                : "Use sleeves other decks have too?",
                [...shared.map(s => `${s.others.join(", ")} ${s.others.length === 1 ? "uses" : "use"} ${s.label} already`
                  + (shared.length === 1 ? "." : ` (chosen for ${s.deck}).`)),
                "Several decks can share one design: just don't play two of them against each other."],
                [{ text: "Use them anyway", kind: "primary", value: "share" }, { text: "Cancel", value: null }]);
              if (choice !== "share" || !assemblySheetHere(ctx)) return;
            }
            ctx.sheet.close({ kit });
          } },
        { text: "Cancel", onclick: () => ctx.sheet.close() },
      ]);
    }
    /** The sleeves choices that give a deck a design other holders have: [{deck, label, others}], each
     * newly chosen design (not the deck's current one) with the decks outside it that use it, and any
     * other deck in this sheet given it too. */
    function sharedSleeves(kit) {
      const out = [];
      for (const form of forms) {
        const id = kit[form.id]?.sleeves;
        if (!id || id === (form.current.sleeves || null)) continue;
        const item = items.find(row => row.id === id && row.kind === "sleeves");
        if (!item) continue;
        const here = forms.filter(other => other !== form && kit[other.id]?.sleeves === id).map(other => other.title);
        const others = [...new Set([...accTaken(item, form.id).others.map(holder => holder.title), ...here])];
        if (others.length) out.push({ deck: form.title, label: item.label, others });
      }
      return out;
    }
    function boxProblem() {
      const selected = new Set(decks.map(deck => deck.id)), chosen = new Map();
      for (const form of forms) {
        const id = form.inputs.deck_box?.value;
        if (id) chosen.set(id, [...(chosen.get(id) || []), form]);
      }
      for (const [id, holders] of chosen) {
        const item = items.find(row => row.id === id && row.kind === "deck_box");
        if (!item || holders.every(form => form.current.deck_box === id)) continue;
        const outside = (item.used_by || []).filter(holder => !selected.has(accHolder(holder.holder))).length;
        if (holders.length + outside > item.quantity) return `There are not enough ${item.label} deck boxes for these choices. Choose another box.`;
      }
      return "";
    }
    function sync() {
      for (const form of forms) draft[form.id] = Object.fromEntries(Object.entries(form.inputs).map(([key, input]) => [key, input.value || null]));
      error.textContent = boxProblem();
      actions();
    }
    function draw() {
      clear(fields); forms.length = 0;
      for (const deck of decks) {
        const part = el("section", { class: "panel" }, el("h3", { text: deck.title }));
        const versions = deck.versions || [deck.version];
        if (versions.length > 1) {
          const list = el("select", { "aria-label": `${deck.title}: built list` }, versions.map(version =>
            el("option", { value: version, selected: version === deck.version, text: listName(version) })));
          list.value = deck.version;
          list.addEventListener("change", () => {
            if (!assemblySheetHere(ctx) || list.value === deck.version) return;
            sync(); ctx.sheet.close();
            const picked = view.selected.find(item => item.id === deck.id);
            if (picked) {
              picked.version = list.value;
              delete picked.sideboard;
              delete picked.prefer;
              view.sideboardChoosing?.delete(picked.id);
            }
            packChanged(view);
            // The review's awaiting caller clears reviewing before the chooser can become editable.
            Promise.resolve().then(() => packRevealChooser(view));
          });
          part.append(el("label", { class: "field" }, el("span", { text: "Built list" }), list,
            el("small", { class: "field-hint", text: "Changing the list returns to the plan so you can check its cards." })));
        } else part.append(el("p", { text: listName(deck.version) }));
        const packed = ctx.data.decks.find(item => item.id === deck.id), scope = packed?.build_scope;
        if (scope) {
          part.append(el("p", { class: "pack-review-scope", text: `${scope.label}: `
            + `${plural(scope.main_count, "main-deck card")} + ${scope.sideboard_count} of ${scope.sideboard_intended} intended sideboard cards.` }));
          if (scope.return_count) part.append(el("div", { class: "box box-warn" },
            el("p", { text: `Put back ${plural(scope.return_count, "card")} from the previous assembly. Confirm these removals before marking built.` }),
            el("ul", {}, (packed.returns || []).map(row => el("li", { text: `${row.quantity} x ${row.name}` })))));
          const intent = remainingIntentPart(packed.remaining_intent);
          if (intent) part.append(intent);
        }
        if (deck.kit?.editable) {
          const form = { id: deck.id, title: deck.title, inputs: {}, current: deck.kit };
          forms.push(form);
          for (const field of ["sleeves", "deck_box"]) {
            const available = items.filter(item => item.kind === field && accessoryUsable(item, deck.owner));
            const current = deck.kit[field] || "", proposed = draft[deck.id]?.[field];
            const value = proposed !== undefined && (!proposed || available.some(item => item.id === proposed) || proposed === current)
              ? proposed || "" : current;
            const input = el("select", { "aria-label": `${deck.title}: ${field === "sleeves" ? "sleeves" : "deck box"}` },
              el("option", { value: "", text: "Not recorded" }),
              current && !available.some(item => item.id === current) ? el("option", { value: current, text: `Keep current: ${current}` }) : null,
              available.map(item => {
                const need = deck.kit.need;
                const fits = field === "sleeves" ? item.quantity >= need
                  ? `${need} needed · ${item.quantity} owned · ${item.quantity - need} spare`
                  : `${need - item.quantity} sleeves short`
                  : item.capacity != null && item.capacity < need ? `Too small: holds ${item.capacity}, ${need} cards here`
                    : item.capacity != null ? `Holds ${item.capacity}` : "";
                const taken = accTaken(item, deck.id);
                const selected = new Set(decks.map(chosen => chosen.id));
                const outside = (item.used_by || []).filter(holder => !selected.has(accHolder(holder.holder))).length;
                const unavailable = field === "deck_box" && outside >= item.quantity;
                return el("option", { value: item.id, disabled: unavailable && item.id !== current,
                  text: [item.label, fits, (taken.taken || (field === "sleeves" && taken.others.length)) && item.id !== current ? accTakenWords(taken) : ""].filter(Boolean).join(" · ") });
              }));
            input.value = value;
            form.inputs[field] = input;
            input.addEventListener("change", sync);
            part.append(el("label", { class: "field" }, el("span", { text: field === "sleeves" ? "Sleeves" : "Deck box" }), input));
          }
        } else if (deck.kit_why_not) part.append(el("p", { class: "sub", text: deck.kit_why_not }));
        fields.append(part);
      }
      sync();
    }
    async function load() {
      if (!assemblySheetHere(ctx)) return;
      loading = true; failed = false; error.textContent = "";
      clear(fields).append(loadingBox("Loading sleeves and deck boxes…", { small: true })); actions();
      try {
        const data = await api("/api/accessories");
        if (!assemblySheetHere(ctx)) return;
        items = data.items || []; loading = false; draw();
      } catch (failure) {
        if (!assemblySheetHere(ctx)) return;
        loading = false; failed = true; clear(fields); error.textContent = failure.message; actions();
      }
    }
    if (loading) load(); else { loading = false; draw(); }
  });
}

/** Stand-ins are physical markers, so a saved choice never changes the logical list. */
function packStandinsPart(view, deck) {
  const info = deck.standins;
  if (!info) return null;
  const mappings = info.rows || [], retired = info.retired || [];
  if (!mappings.length && !retired.length && !(info.needs || []).length && !(info.warnings || []).length) return null;
  const part = el("div", { class: "pack-standins" }, el("h3", { text: "Stand-ins" }));
  if (mappings.length) part.append(el("ul", {}, mappings.map(row => el("li", {},
    `${row.qty} × ${row.using || "Any spare card"} stands for `,
    view.cards[row.for] ? cardLink({ name: row.for, card: view.cards[row.for] }, "packing-standins") : row.for))));
  if (retired.length) part.append(el("ul", {}, retired.map(row => el("li", { text:
    (row.reason === "real_available" ? `${row.qty} × ${row.for} is now available.`
      : `${row.qty} × ${row.using || "Any spare card"} will no longer stand for ${row.for}.`)
    + " Finish this plan to record the change." }))));
  if ((info.warnings || []).length) add(part, [warningsBox(info.warnings, "Check stand-ins")]);
  if (info.editable && (info.needs || []).length) part.append(el("button", { type: "button", class: "btn", text: "Choose stand-ins",
    onclick: () => { if (assemblyActive(view) && !view.saving) openPackStandins(view, deck); } }));
  return part;
}

function openPackStandins(view, deck) {
  if (!assemblyActive(view) || view.saving || view.reviewing || !deck.standins?.editable
      || !view.data.decks.includes(deck)) return null;
  const ctx = openAssemblySheet(view, `Stand-ins for ${deck.title}`), info = deck.standins;
  const error = el("p", { class: "form-error", role: "alert" }), inputs = [];
  let sending = false, stale = false;
  ctx.sheet.body.append(el("p", { text: "A stand-in represents the missing card. Its rules and your decklist stay the same; a named stand-in uses one of your free physical copies." }));
  for (const [index, need] of (info.needs || []).entries()) {
    const select = el("select", { "aria-label": `Stand-in for ${need.for}, group ${index + 1}` },
      el("option", { value: "", text: "Any spare card" }),
      (info.candidates || []).filter(item => item.free >= need.qty || item.name === need.suggestion).map(item =>
        el("option", { value: item.name, text: `${item.name} (${item.free} free)` })));
    select.value = need.suggestion || "";
    inputs.push({ need, select });
    ctx.sheet.body.append(el("label", { class: "field" }, el("span", { text: `${need.qty} × ${need.for}` }), select));
  }
  ctx.sheet.body.append(error);
  function actions() {
    sheetActions(ctx.sheet, [stale ? { text: "Refresh plan", kind: "primary", onclick: () => {
      if (!assemblySheetHere(ctx)) return;
      ctx.sheet.close(); packChanged(view); clearTimeout(view.timer); view.run();
    } } : { text: "Save stand-ins", kind: "primary", disabled: sending, onclick: save },
      { text: "Cancel", onclick: () => ctx.sheet.close() }]);
  }
  async function save() {
    if (!assemblySheetHere(ctx) || sending || stale) return;
    sending = true; inputs.forEach(input => { input.select.disabled = true; }); error.textContent = ""; actions();
    try {
      await apiWrite("/api/assembly/standins", { id: deck.id, version: deck.version, sha256: info.sha256,
        decks: view.selected.map(item => ({ ...item })), fingerprint: ctx.data.completion.fingerprint,
        rows: inputs.map(({ need, select }) => ({ for: need.for, using: select.value || null, qty: need.qty })) });
      if (!assemblySheetHere(ctx)) return;
      state.library = null; ctx.sheet.close(); packChanged(view); clearTimeout(view.timer);
      view.run();
    } catch (failure) {
      if (!assemblySheetHere(ctx)) return;
      stale = failure.status === 409;
      error.textContent = failure.message + (stale ? " Refresh the plan before choosing again." : "");
    } finally {
      sending = false;
      if (assemblySheetHere(ctx)) { inputs.forEach(input => { input.select.disabled = stale; }); actions(); }
    }
  }
  actions();
  return ctx;
}
