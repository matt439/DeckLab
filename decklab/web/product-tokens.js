/* A whole owned/intact product's packed-token record. Holder identity comes only from API producer metadata. */
"use strict";

function productTokenEvidence(packed) {
  const product = packed?.product, hash = value => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
  if (!product || typeof product !== "object" || Array.isArray(product)
      || typeof product.stem !== "string" || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(product.stem)
      || product.stem === "status" || !hash(product.status_sha256)
      || !(packed.tokens_sha256 === null || hash(packed.tokens_sha256))
      || typeof packed.written !== "boolean" || typeof packed.editable !== "boolean"
      || !Array.isArray(packed.choices) || packed.choices.length > 2000 || !Array.isArray(packed.lines)) return null;
  const named = text => typeof text === "string" && text.trim() && !/[\u0000-\u001f\u007f]/.test(text);
  const seen = new Set();
  for (const choice of packed.choices) {
    if (!choice || !Number.isSafeInteger(choice.row) || choice.row < 0 || seen.has(choice.row) || !named(choice.front)
        || !(choice.back === "" || named(choice.back)) || typeof choice.set !== "string" || typeof choice.number !== "string"
        || !Number.isSafeInteger(choice.quantity) || choice.quantity < 1 || !Number.isSafeInteger(choice.free)
        || choice.free < 0 || choice.free > choice.quantity || !Number.isSafeInteger(choice.packed) || choice.packed < 0) return null;
    seen.add(choice.row);
  }
  if (packed.lines.some(line => !line || !named(line.text))) return null;
  return { stem: product.stem, expect: product.status_sha256, tokens_sha256: packed.tokens_sha256 };
}

function productTokensVisible() {
  return Boolean(state.profile) && ownSpace() === HOME_SPACE && seesHomeInventory(state.may);
}

/** Same TokenCardLine identity/order as the server: finishes/details do not split a packed line. */
function productTokenText(choices, cards) {
  const lines = new Map();
  for (const card of cards) {
    const choice = choices.find(item => item.row === card.row);
    const printed = Boolean(choice.set && choice.number);
    const values = [choice.front, choice.back || "", printed ? choice.set.toLowerCase() : "", printed ? choice.number : ""];
    const key = JSON.stringify(values), line = lines.get(key) || { values, quantity: 0 };
    line.quantity += card.quantity; lines.set(key, line);
  }
  return [...lines.values()].map(({ values: [front, back, set, number], quantity }) =>
    quantity + " " + front + (back ? " // " + back : "") + (set ? " (" + set.toUpperCase() + ") " + number : "")).join("; ");
}

function productTokensOwner(ctx) {
  return ctx.token === routeToken && ctx.profile === state.profile?.id && ctx.hash === location.hash
    && ctx.screen === deckScreen && ctx.root.isConnected && productTokensVisible()
    && ctx.data.tokens?.packed === ctx.packed && JSON.stringify(ctx.packed) === ctx.signature;
}

/** Existing deckPackedTokens calls this only for an explicit product relationship. */
function productPackedTokens(data) {
  if (!productTokensVisible()) return null;
  const packed = data.tokens?.packed, evidence = productTokenEvidence(packed);
  const root = el("div", { class: "deck-tokens-packed product-tokens" });
  const error = packed?.error || (!evidence ? "The product's packed-token record cannot be checked. Reload the product before changing it." : "");
  const words = error || (packed.written ? packed.lines.length
    ? "Packed for the whole product: " + packed.lines.map(line => line.text).join("; ")
    : "The product has an empty packed-token record; check its physical token cards."
    : "Packed token cards are not recorded for this product. The shared-card warning assumes one card per token row it uses; check the cards in the box before recording quantities.");
  root.append(el("p", { class: error || !packed?.written ? "box box-warn" : "sub", text: words }),
    el("p", { class: "sub", text: "One record covers the whole product, including all its decks." }));
  if (evidence && packed.editable && mayDo("products") && !packed.error) {
    const ctx = { data, packed, evidence, root, signature: JSON.stringify(packed), hash: location.hash,
      screen: deckScreen, token: routeToken, profile: state.profile?.id, busy: false };
    const button = el("button", { type: "button", class: "btn btn-quiet", text: "Change product packed token cards.",
      onclick: () => {
        if (productTokensOwner(ctx) && !ctx.busy && !ctx.confirmed && !ctx.needsRefresh && button.isConnected && root.contains(button)
            && !document.querySelector("dialog[open]")) openProductPackedTokens(ctx);
      } });
    root.append(button);
  } else if (packed?.why_not) root.append(el("p", { class: "sub", text: packed.why_not }));
  return root;
}

/** Refresh only the original page after the sheet's temporary history entry has actually closed. */
function productTokensAfterClose(ctx) {
  if (ctx.refreshed) return;
  const entry = ctx.sheet.entry;
  const stop = () => {
    window.removeEventListener("popstate", landed);
    window.removeEventListener("hashchange", stop);
  };
  const landed = () => {
    stop();
    if (!ctx.refreshed && productTokensOwner(ctx) && (!entry || history.state?.sheet !== entry.token
        && history.state?.pos === entry.pos - 1)) { ctx.refreshed = true; route(); }
  };
  if (!productTokensOwner(ctx)) return;
  if (!entry || entry.fromHistory || history.state?.sheet !== entry.token) landed();
  else {
    window.addEventListener("popstate", landed);
    window.addEventListener("hashchange", stop);
  }
}

function openProductPackedTokens(ctx) {
  if (!productTokensOwner(ctx) || ctx.busy || ctx.confirmed || ctx.needsRefresh || !ctx.packed.editable || !mayDo("products")) return null;
  ctx.busy = true;
  ctx.confirmed = ctx.needsRefresh = ctx.refreshed = false;
  let pending = false;
  const sheet = ctx.sheet = openSheet("Product packed token cards", { onClose: () => {
    productStorageSheets.delete(sheet); ctx.busy = pending;
    if (ctx.confirmed || ctx.needsRefresh) productTokensAfterClose(ctx);
  } });
  productStorageSheets.add(sheet); // Existing route/profile/away lifecycle closes product sheets.
  const current = () => !sheet.closed && productTokensOwner(ctx);
  const here = () => current() && [...document.querySelectorAll("dialog[open]")].at(-1) === sheet.dialog;
  const inputs = [];
  const message = el("p", { class: "form-error", role: "alert", tabindex: "-1", hidden: true });
  sheet.body.append(el("p", { text: "Check the physical token cards kept with the whole product, including all its decks. These quantities reserve existing cards; they do not add cards to your collection." }),
    el("p", { class: "sub", text: "Clearing this record leaves its packed quantities unknown. It does not record that the product packs no token cards." }),
    el("ul", { class: "pack-plain deck-packed-choices" }, ctx.packed.choices.map(choice => {
      const id = "product-packed-" + sheet.heading.id + "-" + choice.row;
      // A legacy estimate is not a checked quantity. Never silently clamp an overcommitted saved record.
      let accepted = String(ctx.packed.written ? choice.packed : 0);
      const input = el("input", { id, type: "number", inputmode: "numeric", min: 0, max: choice.free, step: 1,
        value: accepted, onchange: () => {
          if (!here() || pending || ctx.confirmed || ctx.needsRefresh) { input.value = accepted; return; }
          accepted = input.value;
        } });
      inputs.push([choice, input]);
      const name = choice.front + (choice.back ? " / " + choice.back : "") + (choice.set ? " (" + choice.set.toUpperCase() + " " + choice.number + ")" : "");
      const elsewhere = choice.quantity - choice.free;
      return el("li", {}, el("label", { for: id, text: name + ": " + plural(choice.quantity, "card")
        + (elsewhere ? ", " + elsewhere + " in other holders" : "") }), " ", input);
    })), message);
  function actions() {
    sheetActions(sheet, ctx.confirmed ? [{ text: "Done", kind: "primary", onclick: () => { if (here()) sheet.close(); } }]
      : ctx.needsRefresh ? [{ text: "Reload product", kind: "primary", onclick: () => { if (here() && !pending) sheet.close(); } },
        { text: "Close", onclick: () => sheet.close() }]
        : [{ text: "Cancel", disabled: pending, onclick: () => sheet.close() },
          ctx.packed.written ? { text: "Clear packed record", disabled: pending, onclick: () => save(true) } : null,
          { text: "Save", kind: "primary", disabled: pending || !inputs.length, onclick: () => save(false) }]);
  }
  async function save(clearRecord) {
    if (!here() || pending || ctx.confirmed || ctx.needsRefresh || !ctx.packed.editable || !mayDo("products")) return;
    const cards = [];
    if (!clearRecord) for (const [choice, input] of inputs) {
      const value = String(input.value).trim(), quantity = Number(value);
      if (!value || !Number.isSafeInteger(quantity) || quantity < 0 || quantity > choice.free) {
        message.textContent = "Choose a whole quantity from 0 to " + choice.free + " for " + choice.front + ".";
        message.hidden = false; input.focus(); return;
      }
      if (quantity) cards.push({ row: choice.row, quantity });
    }
    const trigger = document.activeElement;
    const expectedText = productTokenText(ctx.packed.choices, cards);
    const focusOwned = () => document.activeElement === trigger || document.activeElement === document.body || !document.activeElement?.isConnected;
    pending = true; message.hidden = true; inputs.forEach(([, input]) => { input.disabled = true; }); actions();
    try {
      const answer = await apiWrite("/api/product/token-cards", { ...ctx.evidence, cards });
      if (typeof answer.saved !== "boolean" || answer.stem !== ctx.evidence.stem || typeof answer.token_cards !== "string"
          || !/^[a-f0-9]{64}$/.test(answer.status_sha256 || "") || answer.tokens_sha256 !== ctx.evidence.tokens_sha256
          || answer.token_cards !== expectedText) throw new Error("The save result could not be confirmed.");
      state.library = null;
      if (!productTokensOwner(ctx)) return;
      ctx.confirmed = true;
      if (sheet.closed) { productTokensAfterClose(ctx); return; }
      const confirmation = el("p", { role: "status", tabindex: "-1", text: cards.length
        ? "Packed token cards are recorded for the whole product."
        : "The packed-token record is cleared. Its packed quantities are unknown until recorded again." });
      clear(sheet.body).append(confirmation); actions();
      if (here() && focusOwned()) confirmation.focus();
    } catch (failure) {
      state.library = null; // An uncertain response may follow a committed write.
      if (!productTokensOwner(ctx)) return;
      ctx.needsRefresh = true;
      if (sheet.closed) { productTokensAfterClose(ctx); return; }
      message.textContent = failure.status ? failure.message + " Reload the product before saving again."
        : "The save result could not be confirmed. Reload the product before saving again.";
      message.hidden = false;
      if (here() && focusOwned()) message.focus();
    } finally {
      pending = false;
      ctx.busy = !sheet.closed;
      if (current()) actions();
    }
  }
  actions();
  return sheet;
}
