/* Optional precon token rows: explicit physical quantities and one checked face per source entry. */
"use strict";

const PRECON_TOKEN_LIMIT = 250; // lib/precons.MAX_COUNT and precon_tokens.MAX_ROWS

/** New option metadata supersedes legacy declared-count offers; malformed options never fall back. */
function preconTokenOffer(preview) {
  const offer = preview?.token_import;
  const hash = value => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
  const named = text => typeof text === "string" && text.trim() === text && text.length > 0 && !/[\u0000-\u001f\u007f]/.test(text);
  const count = value => Number.isSafeInteger(value) && value >= 1 && value <= PRECON_TOKEN_LIMIT;
  if (!offer || offer.editable !== true || !(offer.sha256 === null || hash(offer.sha256)) || !hash(offer.source_sha256)) return null;
  if (Object.hasOwn(offer, "options")) {
    if (offer.choices_ready !== true || !Array.isArray(offer.choice_problems) || offer.choice_problems.length
        || !Array.isArray(offer.options) || !offer.options.length || offer.options.length > PRECON_TOKEN_LIMIT
        || new Set(offer.options.map(option => option?.source_row)).size !== offer.options.length
        || !offer.options.every(option => option && Number.isSafeInteger(option.source_row) && option.source_row > 0
          && named(option.source_name) && (option.quantity === null || count(option.quantity))
          && Array.isArray(option.fronts) && option.fronts.length >= 1 && option.fronts.length <= 2
          && option.fronts.every(named) && new Set(option.fronts).size === option.fronts.length)) return null;
    return offer;
  }
  if (offer.ready !== true || !Array.isArray(offer.rows) || !offer.rows.length || offer.rows.length > PRECON_TOKEN_LIMIT
      || !Array.isArray(offer.problems) || offer.problems.length
      || new Set(offer.rows.map(row => row?.source_row)).size !== offer.rows.length
      || !Number.isSafeInteger(offer.cards) || offer.cards < 1
      || !offer.rows.every(row => row && named(row.front) && count(row.quantity)
        && Number.isSafeInteger(row.source_row) && row.source_row > 0)
      || offer.rows.reduce((sum, row) => sum + row.quantity, 0) !== offer.cards) return null;
  return offer;
}

function preconTokenOwner(ctx, choice) {
  return !ctx.sheet.closed && !ctx.tokenPreviewStale && colActive(ctx.cv) && ctx.tokenChoice === choice
    && ctx.cv.editable && canEditSpace(choice.space) && ctx.cv.root === choice.root
    && routeToken === choice.token && state.profile?.id === choice.profile
    && ctx.preview === choice.preview && ctx.seq === choice.seq && ctx.cv.space === choice.space
    && location.hash === choice.hash && choice.preview.sha256 === choice.collectionSha
    && choice.preview.deck.file === choice.file && preconTokenOffer(choice.preview) === choice.offer
    && JSON.stringify(choice.offer) === choice.signature && choice.node.isConnected && ctx.area.contains(choice.node);
}

function preconTokensBusy(ctx, disabled) {
  const choice = ctx.tokenChoice;
  if (!choice) return;
  choice.node.disabled = disabled;
  for (const input of choice.inputs) input.disabled = disabled || !choice.node.checked;
}

/** One error stays beside the physical review, and only an owned current control receives focus. */
function preconTokenProblem(ctx, choice, words, control) {
  choice.message.textContent = words; choice.message.hidden = false;
  if (preconTokenOwner(ctx, choice) && [...document.querySelectorAll("dialog[open]")].at(-1) === ctx.sheet.dialog) control.focus();
}

/** The positive entries stay separate even when two entries choose the same canonical face. */
function preconTokenSelection(ctx) {
  const choice = ctx.tokenChoice;
  if (!choice || !choice.accepted || !choice.node.checked || !preconTokenOwner(ctx, choice)
      || [...document.querySelectorAll("dialog[open]")].at(-1) !== ctx.sheet.dialog) return null;
  const offer = choice.offer;
  if (!choice.options) return { offer, cards: offer.cards, rows: offer.rows.length };
  if (choice.fields.hidden) return null;
  const choices = [];
  for (const row of choice.options) {
    if (!row.quantity.isConnected || !ctx.area.contains(row.quantity)
        || row.front && (!row.front.isConnected || !ctx.area.contains(row.front))) return null;
    const text = row.quantity.value.trim(), quantity = Number(text);
    if (!/^\d+$/.test(text) || !Number.isSafeInteger(quantity) || quantity < 0 || quantity > PRECON_TOKEN_LIMIT) {
      preconTokenProblem(ctx, choice, "Enter a whole physical quantity from 0 to " + PRECON_TOKEN_LIMIT
        + " for entry " + row.option.source_row + ". Use 0 to skip it.", row.quantity); return null;
    }
    const front = row.front ? row.front.value : row.option.fronts[0];
    if (quantity > 0 && !row.option.fronts.includes(front)) {
      preconTokenProblem(ctx, choice, "Choose the face to record for entry " + row.option.source_row + ".", row.front); return null;
    }
    if (front && !row.option.fronts.includes(front)) return null;
    choices.push({ source_row: row.option.source_row, front, quantity });
  }
  const positive = choices.filter(row => row.quantity > 0), cards = positive.reduce((sum, row) => sum + row.quantity, 0);
  if (!cards) {
    preconTokenProblem(ctx, choice, "Choose at least one physical token card, or untick Add its token cards too to add only the playable cards.", choice.node);
    return null;
  }
  choice.message.hidden = true;
  return { offer, choices, cards, rows: positive.length };
}

/** Complete rows are reviewed locally; unknown counts remain blank and combined names remain one entry. */
function preconTokenChoice(ctx) {
  ctx.tokenChoice = null; ctx.tokenPreviewStale = false;
  const preview = ctx.preview, offer = preconTokenOffer(preview), raw = preview.token_import;
  if (!raw) return null;
  if (!offer || !preview.editable) {
    const problems = Object.hasOwn(raw, "options") ? raw.choice_problems : raw.problems;
    return raw.rows?.length || raw.problems?.length || raw.options?.length || problems?.length
      ? el("div", { class: "box box-warn" }, el("p", { text: "Token cards cannot be added from this preview. Check them on the Tokens page instead." }),
        Array.isArray(problems) ? el("ul", {}, problems.filter(problem => problem && typeof problem.message === "string")
          .map(problem => el("li", { text: problem.message }))) : null) : null;
  }
  const node = el("input", { type: "checkbox" }), inputs = [], options = [];
  const choice = ctx.tokenChoice = { node, inputs, offer, preview, accepted: false, options: Object.hasOwn(offer, "options") ? options : null,
    signature: JSON.stringify(offer), seq: ctx.seq, hash: location.hash, collectionSha: preview.sha256,
    space: ctx.cv.space, file: preview.deck.file, root: ctx.cv.root, token: routeToken, profile: state.profile?.id };
  const current = () => preconTokenOwner(ctx, choice) && !ctx.busy
    && [...document.querySelectorAll("dialog[open]")].at(-1) === ctx.sheet.dialog;
  const fields = choice.fields = el("div", { hidden: true });
  const message = choice.message = el("p", { class: "field-problem", role: "alert", tabindex: "-1", hidden: true });
  let accepted = false;
  node.addEventListener("change", () => {
    if (!current()) { node.checked = accepted; return; }
    accepted = choice.accepted = Boolean(node.checked); fields.hidden = !accepted; message.hidden = true; preconTokensBusy(ctx, false);
  });
  if (!choice.options) return el("section", { class: "precon-tokens" },
    el("label", { class: "choice" }, node, el("span", { text: "Add its token cards too (" + plural(offer.cards, "card") + ")" })),
    el("p", { class: "sub", text: "Added as separate rows for checking. Printing, finish and reverse face stay unconfirmed; check the physical cards afterward." }),
    el("ul", {}, offer.rows.map(row => el("li", { text: row.quantity + " x " + row.front }))));
  function guarded(input) {
    let value = input.value;
    const changed = () => {
      if (!current() || !node.checked || !input.isConnected || !ctx.area.contains(input)) input.value = value;
      else { value = input.value; message.hidden = true; }
    };
    input.addEventListener("input", changed); input.addEventListener("change", changed); inputs.push(input); return input;
  }
  fields.append(el("ol", { class: "pack-plain" }, offer.options.map(option => {
    const id = "precon-token-" + ctx.sheet.heading.id + "-" + option.source_row;
    const quantity = guarded(el("input", { id: id + "-quantity", type: "number", inputmode: "numeric", min: 0,
      max: PRECON_TOKEN_LIMIT, step: 1, value: option.quantity === null ? "" : String(option.quantity), disabled: true,
      placeholder: "Enter physical quantity" }));
    const front = option.fronts.length > 1 ? guarded(el("select", { id: id + "-face", disabled: true },
      el("option", { value: "", text: "Choose a face" }), option.fronts.map(name => el("option", { value: name, text: name })))) : null;
    if (front) front.value = "";
    options.push({ option, quantity, front });
    return el("li", {}, el("p", { text: "Source entry " + option.source_row + ": " + option.source_name }),
      el("label", { class: "field", for: quantity.id }, el("span", { text: "Physical cards for entry " + option.source_row }), quantity),
      el("p", { class: "field-hint", text: option.quantity === null ? "The source does not declare a physical quantity. Enter your checked count, or 0 to skip."
        : "Source declares " + option.quantity + "; confirm the physical count, or enter 0 to skip." }),
      front ? el("label", { class: "field", for: front.id }, el("span", { text: "Face to record for entry " + option.source_row }), front)
        : el("p", { class: "sub", text: "Record as: " + option.fronts[0] }));
  })), message);
  return el("section", { class: "precon-tokens" },
    el("label", { class: "choice" }, node, el("span", { text: "Add its token cards too (review physical quantities)" })),
    el("p", { class: "box box-warn", text: "Source entries may describe two faces of the same physical card. Count that card once and set the other entry to 0. Deck Lab does not pair entries or merge them automatically." }),
    el("p", { class: "sub", text: "Review every entry. Each positive quantity becomes one separate unconfirmed row using only the chosen face. Printing, finish and reverse face stay unknown." }), fields);
}
