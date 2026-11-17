/* Small goal-based changes from Considering. Suggestions read only; a reviewed choice is a
 * linked local Planned/Considering draft. Normal editor checks, Save and testing stay explicit. */
"use strict";

const SMALL_SWAP_GOALS = [["earlier", "Get going sooner"], ["draw", "Draw more cards"], ["answers", "Find more answers"]];

function smallSwapSuggestionsOffered(data) {
  const s = data?.summary;
  return !!(s && s.kind === "casual" && data.version === "target" && !s.read_only && canEditDeck(s)
    && seesInventory(s.space || deckSpaceOf(s.id)) && Array.isArray(data.considering?.lines)
    && Array.isArray(data.sections?.Deck) && data.sections.Deck.reduce((n, line) => n + line.qty, 0) === 60);
}

function smallSwapHere(ctx, control = null) {
  const o = ctx.owner, sheet = ctx.sheet;
  return !sheet.closed && sheet.dialog.isConnected && sheet.dialog.getAttribute("open") !== null
    && routeToken === o.token && location.hash === o.hash && state.profile === o.profile
    && state.profile?.id === o.profileId && (state.profile?.space || HOME_SPACE) === o.space
    && deckScreen === o.screen && (!o.screen || o.screen.data === ctx.data)
    && ctx.data.summary === o.summary && ctx.data.sections === o.sections && ctx.data.version === "target"
    && document.getElementById("main") === o.main && o.main?.isConnected
    && sheet.body === o.body && sheet.foot === o.foot && smallSwapSuggestionsOffered(ctx.data)
    && (!control || control.isConnected && (o.body.contains(control) || o.foot.contains(control))
      && keyboardDialog() === sheet.dialog);
}

function smallSwapInput(ctx) {
  return { id: ctx.data.summary.id, version: "target", goal: ctx.goal.value,
    protected: ctx.protected.filter(input => input.checked).map(input => input.value) };
}

function openSmallSwapSuggestions(data) {
  if (!smallSwapSuggestionsOffered(data)) return null;
  const sheet = openSheet({ title: "Suggest a small swap", side: true });
  const ctx = { data, sheet, seq: 0, answer: null, protected: [] };
  ctx.owner = { token: routeToken, hash: location.hash, profile: state.profile, profileId: state.profile?.id,
    space: state.profile?.space || HOME_SPACE, screen: deckScreen, summary: data.summary, sections: data.sections,
    main: document.getElementById("main"), body: sheet.body, foot: sheet.foot };
  const goalId = `${sheet.heading.id}-goal`;
  ctx.goal = el("select", { id: goalId, class: "small-swap-goal" }, SMALL_SWAP_GOALS.map(([value, text]) =>
    el("option", { value, text })));
  ctx.goal.value = "earlier";
  const keep = el("fieldset", { class: "small-swap-protected" }, el("legend", { text: "Cards to leave in the deck" }));
  const names = [...new Set(data.sections.Deck.map(line => line.card?.name || line.name))].sort((a, b) => a.localeCompare(b));
  names.forEach((name, index) => {
    const id = `${sheet.heading.id}-keep-${index}`;
    const input = el("input", { id, type: "checkbox", class: "small-swap-protect", value: name });
    ctx.protected.push(input);
    keep.append(el("label", { for: id, class: "small-swap-keep" }, input, el("span", { text: name })));
  });
  ctx.message = el("p", { class: "sub small-swap-message", role: "status", "aria-live": "polite" });
  ctx.results = el("div", { class: "small-swap-results" });
  sheet.body.append(el("p", { class: "sub", text:
    "Choose a goal and any cards to keep. Suggestions start with free copies on hand from Considering. One change is the default; nothing runs or saves automatically." }),
    el("label", { for: goalId, text: "What would you like to improve?" }), ctx.goal,
    el("details", { class: "small-swap-keep-details" }, el("summary", { text: "Keep these cards" }), keep), ctx.message, ctx.results);
  const invalidate = () => {
    if (!smallSwapHere(ctx)) return;
    ctx.seq += 1; ctx.answer = null; clear(ctx.results); ctx.message.textContent = "Choose Suggest to use these choices.";
    ctx.suggest.disabled = false;
  };
  ctx.goal.addEventListener("change", invalidate);
  ctx.protected.forEach(input => input.addEventListener("change", invalidate));
  ctx.suggest = el("button", { type: "button", class: "btn btn-primary", text: "Suggest", onclick: () => loadSmallSwaps(ctx) });
  sheet.foot.append(el("button", { type: "button", class: "btn", text: "Done", onclick: () => sheet.close() }), ctx.suggest);
  return ctx;
}

async function loadSmallSwaps(ctx) {
  if (!smallSwapHere(ctx, ctx.suggest) || ctx.suggest.disabled) return;
  const seq = ++ctx.seq, body = smallSwapInput(ctx), signature = JSON.stringify(body), focused = document.activeElement === ctx.suggest;
  ctx.answer = null; clear(ctx.results); ctx.suggest.disabled = true; ctx.message.textContent = "Looking for a small change…";
  try {
    const answer = await apiWrite("/api/deck/small-swaps", body);
    if (!smallSwapHere(ctx, ctx.suggest) || seq !== ctx.seq || JSON.stringify(smallSwapInput(ctx)) !== signature) return;
    if (!answer || answer.deck_id !== body.id || answer.version !== "target" || answer.goal !== body.goal
        || typeof answer.sha256 !== "string" || !Array.isArray(answer.proposals)) throw new Error("The suggestion could not be read.");
    ctx.answer = answer;
    ctx.message.textContent = answer.proposals.length ? "Choose one idea to try. These are suggestions, not measured improvements."
      : answer.reason || "No small change fits these choices. Try another goal or add alternatives to Considering.";
    answer.proposals.slice(0, 3).forEach((proposal, index) => ctx.results.append(smallSwapProposal(ctx, proposal, index)));
    if (focused && document.activeElement === document.body) {
      const target = answer.proposals.length ? ctx.results : ctx.message;
      target.setAttribute("tabindex", "-1"); target.focus();
    }
  } catch (error) {
    if (smallSwapHere(ctx, ctx.suggest) && seq === ctx.seq) {
      ctx.message.textContent = error instanceof ApiError && [400, 403, 404].includes(error.status)
        ? "Suggestions are unavailable for this deck. Reload the deck before trying again."
        : "Suggestions couldn't load. Your choices are kept; choose Suggest to try again.";
    }
  } finally {
    if (smallSwapHere(ctx) && seq === ctx.seq) {
      ctx.suggest.disabled = false;
      if (focused && document.activeElement === document.body) ctx.suggest.focus({ preventScroll: true });
    }
  }
}

function smallSwapProposal(ctx, proposal, index) {
  const row = el("section", { class: "box small-swap-proposal", "aria-labelledby": `${ctx.sheet.heading.id}-idea-${index}` });
  const cuts = proposal.cuts || [], adds = proposal.adds || [];
  if (cuts.length !== 1 || adds.length !== 1) return row;
  const cut = cuts[0], addition = adds[0];
  const cutLine = ctx.data.sections.Deck.find(line => (line.card?.name || line.name) === cut.name);
  const quantityId = `${ctx.sheet.heading.id}-qty-${index}`;
  const quantity = el("select", { id: quantityId, class: "small-swap-quantity" },
    el("option", { value: "1", text: "1 copy (start here)" }),
    proposal.max_qty === 2 ? el("option", { value: "2", text: "2 copies of this swap" }) : null);
  quantity.value = "1";
  const cards = el("div", { class: "small-swap-cards", "aria-live": "polite" });
  const drawCards = () => clear(cards).append(
    cardRow(cutLine?.card, { qty: Number(quantity.value), name: cut.name, meta: "Cut", viewerGroup: "small-swaps" }),
    cardRow(addition.card, { qty: Number(quantity.value), name: addition.name, meta: "Add from Considering · free on hand", viewerGroup: "small-swaps" }));
  drawCards();
  quantity.addEventListener("change", () => { if (smallSwapHere(ctx, quantity)) drawCards(); });
  row.append(el("h3", { id: `${ctx.sheet.heading.id}-idea-${index}`, text: `Try ${addition.name} for ${cut.name}` }), cards,
    el("p", { text: proposal.reason }), el("p", {}, el("b", { text: "Trade-off: " }), proposal.trade_off),
    el("label", { for: quantityId, text: "Copies to try" }), quantity,
    el("p", { class: "sub", text: "Two copies still test this one idea. Try it at the table, or review the draft before saving or starting a test." }));
  const actions = el("div", { class: "small-swap-actions" });
  for (const [text, test] of [["Review in editor", false], ["Test this change", true]]) {
    const button = el("button", { type: "button", class: "btn", text, onclick: () => {
      if (smallSwapHere(ctx, button)) reviewSmallSwap(ctx, proposal, Number(quantity.value), test, button, quantity);
    } });
    actions.append(button);
  }
  row.append(actions);
  return row;
}

function smallSwapSameLine(a, b) {
  return String(a.card?.name || a.name).toLowerCase() === String(b.card?.name || b.name).toLowerCase()
    && String(a.set || "").toLowerCase() === String(b.set || "").toLowerCase()
    && String(a.number || "") === String(b.number || "") && (a.finish || "nonfoil") === (b.finish || "nonfoil")
    && (a.category || "") === (b.category || "");
}

/** A complete linked draft, without touching the saved view or local storage. The exact Considering
 * printing/category must still have enough copies; partial cuts or partial promotions never apply. */
function smallSwapDraft(view, proposal, quantity) {
  if (![1, 2].includes(quantity) || quantity > proposal.max_qty || proposal.cuts?.length !== 1 || proposal.adds?.length !== 1
      || proposal.cuts[0].qty !== 1 || proposal.adds[0].qty !== 1 || !view.lists?.target || !Array.isArray(view.lists.considering)) return null;
  const cut = proposal.cuts[0], addition = proposal.adds[0];
  if (String(cut.name).toLowerCase() === String(addition.name).toLowerCase()) return null;
  const lists = Object.fromEntries(Object.entries(view.lists.target).map(([section, lines]) => [section, lines.map(line => ({ ...line }))]));
  const considering = view.lists.considering.map(line => ({ ...line }));
  let left = quantity;
  for (const line of lists.Deck || []) {
    if (String(line.card?.name || line.name).toLowerCase() !== String(cut.name).toLowerCase()) continue;
    const take = Math.min(left, line.qty); left -= take; line.qty -= take;
  }
  if (left) return null;
  lists.Deck = lists.Deck.filter(line => line.qty > 0);
  left = quantity;
  const sources = [];
  for (const line of considering) {
    if (!smallSwapSameLine(line, addition)) continue;
    const take = Math.min(left, line.qty); left -= take; line.qty -= take;
    if (take) sources.push({ ...line, qty: take });
  }
  if (left) return null;
  for (const source of sources) {
    const existing = lists.Deck.find(line => smallSwapSameLine(line, source));
    if (existing) existing.qty += source.qty;
    else lists.Deck.push({ ...source });
  }
  const fields = pickFields(view.fields), prose = proseOf(view);
  return { v: 1, saved: Date.now(), sha256: view.sha256, starting: false,
    base: { lists: view.lists.target, fields, prose, considering: view.lists.considering },
    lists, fields, prose, considering: considering.filter(line => line.qty > 0), addSection: "Deck",
    consideringMoves: sources.map(source => ({ source: sendLine(source), section: "Deck" })),
    promotionReview: false, promotionAccepted: null, promotionAcknowledged: null, promotionUnavailable: false };
}

async function reviewSmallSwap(ctx, proposal, quantity, test, button, quantityControl) {
  if (!smallSwapHere(ctx, button) || button.disabled || ctx.reviewing || !ctx.answer || !ctx.answer.proposals.includes(proposal)) return;
  const answer = ctx.answer, seq = ctx.seq, signature = JSON.stringify(smallSwapInput(ctx));
  const review = ctx.reviewing = {};
  const current = () => smallSwapHere(ctx, button) && ctx.answer === answer && ctx.seq === seq
    && ctx.reviewing === review && smallSwapHere(ctx, quantityControl) && quantityControl.value === String(quantity)
    && JSON.stringify(smallSwapInput(ctx)) === signature;
  const buttons = [...ctx.results.querySelectorAll("button")];
  buttons.forEach(control => { control.disabled = true; });
  try {
    const view = await api(`/api/deck/edit?id=${encodeURIComponent(answer.deck_id)}`);
    if (!current()) return;
    if (view.sha256 !== answer.sha256 || view.id !== answer.deck_id || view.may_save === false) {
      ctx.message.textContent = "The deck changed. Reload it and ask for a fresh suggestion before reviewing this swap.";
      return;
    }
    const draft = smallSwapDraft(view, proposal, quantity);
    if (!draft) { ctx.message.textContent = "This swap no longer fits the deck and Considering list. Ask for a fresh suggestion."; return; }
    const key = draftKey({ mode: "edit", profile: ctx.owner.profileId, id: answer.deck_id, version: "target" });
    const previous = local.get(key);
    if (previous) {
      const choice = await ask("Replace your unsaved changes?", [`Replace your unsaved changes to ${view.title || "this deck"} with this swap?`],
        [{ text: "Keep my changes", value: "keep" }, { text: "Replace them", kind: "primary", value: "replace" }]);
      if (choice !== "replace" || !current() || local.get(key) !== previous) return;
    }
    if (!current()) return;
    if (!local.set(key, JSON.stringify(draft))) {
      ctx.message.textContent = "The swap couldn't be kept on this device. Make the change in the editor instead.";
      return;
    }
    ctx.sheet.close();
    location.hash = `${editHref(answer.deck_id, "target")}${test ? "&test=change" : ""}`;
  } catch (error) {
    if (current()) ctx.message.textContent = "The deck couldn't load for review. Your suggestion is kept; try again.";
  } finally {
    if (ctx.reviewing === review) {
      ctx.reviewing = null;
      buttons.forEach(control => { if (control.isConnected) control.disabled = false; });
    }
  }
}
