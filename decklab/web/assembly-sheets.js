/* Packing choices are reviewed here; only the explicit save changes deck metadata. */
"use strict";

const assemblySheets = new Set();

function closeAssemblySheets(closeChooser = true) {
  for (const sheet of [...assemblySheets]) sheet.close();
  if (closeChooser) closePackingChoosers();
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
      clear(fields).append(loadingBox("Loading sleeves and deck boxes...")); actions();
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
