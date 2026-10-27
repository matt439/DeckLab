/* Usual opponents on the deck Overview. A save changes this deck's choices;
 * reciprocal links are resolved by the server without editing the other decks. */
"use strict";

const deckOpponentSheets = new Set();

function closeDeckOpponentSheets() {
  for (const sheet of [...deckOpponentSheets]) sheet.close();
}

function deckOpponentsSection(data) {
  const editable = !data.summary.read_only && canEditDeck(data.summary);
  if (!(data.usual_opponents || []).length && !editable) return null;
  const section = el("section", { class: "deck-section", id: "sec-opponents", "aria-labelledby": "h-opponents" });
  const token = routeToken, profile = state.profile?.id;
  const here = () => token === routeToken && profile === state.profile?.id && section.isConnected;
  function draw() {
    clear(section).append(el("h2", { id: "h-opponents", text: "Usual opponents" }));
    const opponents = data.usual_opponents || [];
    const choose = editable ? el("button", { type: "button", class: "btn", text: "Choose usual opponents",
      onclick: () => {
        if (!here()) return;
        openDeckOpponents(data.summary.id, answer => {
          if (!here()) return;
          data.usual_opponents = answer.usual_opponents;
          data.summary.usual_opponents = answer.usual_opponents.map(item => item.id);
          draw();
        });
      } }) : null;
    // None chosen: the button that fills the list goes in the empty state with its line.
    section.append(opponents.length
      ? el("ul", {}, opponents.map(item => el("li", {}, el("a", { href: deckHref(item.id), text: item.title }))))
      : emptyBox("No usual opponents chosen yet.", choose));
    if (opponents.length && choose) section.append(choose);
  }
  draw();
  return section;
}

function opponentSheetHere(ctx) {
  return !ctx.sheet.closed && ctx.token === routeToken && ctx.profile === state.profile?.id;
}

function openDeckOpponents(id, onSaved) {
  const sheet = openSheet("Usual opponents", { onClose: () => deckOpponentSheets.delete(sheet) });
  deckOpponentSheets.add(sheet);
  const ctx = { id, sheet, onSaved, token: routeToken, profile: state.profile?.id, generation: 0, sending: false };
  loadDeckOpponents(ctx);
  return ctx;
}

async function loadDeckOpponents(ctx) {
  if (!opponentSheetHere(ctx) || ctx.sending) return;
  const generation = ++ctx.generation;
  clear(ctx.sheet.body).append(loadingBox("Loading usual opponents…"));
  sheetActions(ctx.sheet, [{ text: "Cancel", onclick: () => ctx.sheet.close() }]);
  try {
    const answer = await api(`/api/deck/opponents?id=${encodeURIComponent(ctx.id)}`);
    if (!opponentSheetHere(ctx) || generation !== ctx.generation) return;
    drawDeckOpponents(ctx, answer);
  } catch (failure) {
    if (!opponentSheetHere(ctx) || generation !== ctx.generation) return;
    clear(ctx.sheet.body).append(el("p", { class: "form-error", role: "alert", text: failure.message }));
    sheetActions(ctx.sheet, [{ text: "Try again", onclick: () => loadDeckOpponents(ctx) },
      { text: "Cancel", onclick: () => ctx.sheet.close() }]);
  }
}

function drawDeckOpponents(ctx, answer) {
  const { sheet } = ctx;
  const choices = answer.choices || [], chosen = new Set(answer.opponents || []);
  const initial = [...chosen].sort().join("|");
  const error = el("p", { class: "form-error", role: "alert" });
  const controls = [];
  let conflict = false;
  const changed = () => [...chosen].sort().join("|") !== initial;
  const actions = () => sheetActions(sheet, [
    conflict ? { text: "Reload choices", onclick: () => loadDeckOpponents(ctx) } : null,
    answer.editable && !conflict ? { text: "Save", kind: "primary", disabled: ctx.sending || !changed(), onclick: save } : null,
    { text: "Cancel", onclick: () => sheet.close() },
  ]);
  const list = el("div", {});
  for (const item of choices) {
    const box = el("input", { type: "checkbox", checked: chosen.has(item.id), disabled: !answer.editable,
      onchange: () => {
        if (ctx.sending || !opponentSheetHere(ctx)) return;
        if (box.checked) chosen.add(item.id); else chosen.delete(item.id);
        error.textContent = "";
        actions();
      } });
    controls.push(box);
    list.append(el("label", { class: "choice" }, box, el("span", { text: item.title })));
  }
  add(clear(sheet.body), [el("p", { text: `Choose the decks usually played against ${answer.title}.` }),
    choices.length ? list : el("p", { class: "empty", text: "No other decks are available in this space." }),
    answer.editable ? null : el("p", { class: "sub", text: answer.why_not || "You may view these choices but cannot change them." }),
    (answer.inherited || []).length ? el("div", {}, el("h3", { text: "Also linked from" }),
      el("ul", {}, answer.inherited.map(item => el("li", {}, el("a", { href: deckHref(item.id), text: item.title })))),
      el("p", { class: "sub", text: "These links were chosen on the other deck. Change them there." })) : null,
    error]);
  actions();

  async function save() {
    if (!opponentSheetHere(ctx) || ctx.sending || !answer.editable || !changed() || conflict) return;
    ctx.sending = true;
    controls.forEach(box => { box.disabled = true; });
    error.textContent = "";
    actions();
    try {
      const result = await apiWrite("/api/deck/opponents", { id: ctx.id, sha256: answer.sha256,
        opponents: choices.filter(item => chosen.has(item.id)).map(item => item.id) });
      if (!opponentSheetHere(ctx)) return;
      state.library = null;
      sheet.close();
      if (ctx.onSaved) ctx.onSaved(result);
      toast(result.saved ? "Usual opponents saved." : "Usual opponents are unchanged.");
    } catch (failure) {
      if (!opponentSheetHere(ctx)) return;
      conflict = failure.status === 409;
      error.textContent = failure.message + (conflict ? " Reload the choices, then choose again." : "");
    } finally {
      ctx.sending = false;
      if (opponentSheetHere(ctx)) {
        controls.forEach(box => { box.disabled = !answer.editable || conflict; });
        actions();
      }
    }
  }
}
