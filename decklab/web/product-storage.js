/* An owned product's storage choice, reviewed before one audited inventory change. */
"use strict";

const productStorageSheets = new Set();

function closeProductStorageSheets() {
  for (const sheet of [...productStorageSheets]) sheet.close();
}

function productStorageHere(ctx) {
  return ctx.token === routeToken && ctx.profile === state.profile?.id && ctx.root.isConnected
    && seesInventory(HOME_SPACE);
}

/** Product lists stay public; their physical storage state follows inventory visibility. */
function productStorageSection(data) {
  const id = data.summary.id;
  if (!id.startsWith("product/") || !seesInventory(HOME_SPACE)) return null;
  const root = el("section", { class: "deck-section product-storage", "aria-labelledby": "h-product-storage" },
    el("h2", { id: "h-product-storage", text: "Product storage" }));
  const content = el("div");
  add(root, [content, productBoxDecks(data)]);
  const ctx = { root, content, id, stem: id.split("/")[1], token: routeToken,
    profile: state.profile?.id, seq: 0, busy: false, product: null };
  ctx.refresh = async () => {
    const seq = ++ctx.seq;
    clear(content).append(loadingBox("Loading product storage…", { small: true }));
    try {
      const product = await api(`/api/product?stem=${encodeURIComponent(ctx.stem)}`);
      if (!productStorageHere(ctx) || seq !== ctx.seq) return;
      ctx.product = product;
      drawProductStorage(ctx);
    } catch (failure) {
      if (!productStorageHere(ctx) || seq !== ctx.seq) return;
      if ([403, 404].includes(failure.status)) { root.hidden = true; return; }
      clear(content).append(loadFailed("Product storage", failure, () => {
        if (productStorageHere(ctx)) ctx.refresh();
      }));
    }
  };
  ctx.refresh();
  return root;
}

/** An intact product's decks in its one box (GET /api/deck's box_label, E8-S21), each a link but this one, so
 * its box label's code, which opens the first, reaches them all. None for a single deck or no label. */
function productBoxDecks(data) {
  const label = data.box_label;
  if (!label || !Array.isArray(label.decks) || label.decks.length < 2) return null;
  return el("div", { class: "product-box-decks" },
    el("h3", { text: "Decks in this box" }),
    el("ul", {}, label.decks.map((d) => el("li", {}, d.id === data.summary.id
      ? el("span", { "aria-current": "page", text: `${d.title} (this deck)` })
      : el("a", { href: `#/deck?id=${encodeURIComponent(d.id)}`, text: d.title })))));
}

function drawProductStorage(ctx) {
  const product = ctx.product;
  const words = product.status !== "owned" ? "This product has not been recorded as received."
    : product.intact === "yes" ? "Kept intact: its cards are reserved together as a product."
      : product.intact === "no" ? "Broken up into the shared pool."
        : "Its storage choice has not been recorded.";
  const allowed = product.can_change && mayDo("products");
  const choices = product.intact === "yes" ? ["no"] : product.intact === "no" ? ["yes"] : ["yes", "no"];
  clear(ctx.content).append(el("p", { text: words }));
  if (allowed) ctx.content.append(el("div", { class: "actions" }, choices.map(intact =>
    el("button", { type: "button", class: "btn", text: intact === "yes" ? "Keep intact" : "Break up into storage",
      disabled: ctx.busy || (intact === "yes" && !product.has_decks),
      onclick: () => openProductStorage(ctx, intact) }))));
  if (allowed && !product.has_decks && product.intact !== "yes") ctx.content.append(el("p", { class: "sub",
    text: "Only a product with saved deck lists can be kept intact." }));
  if (!allowed && product.why_not) ctx.content.append(el("p", { class: "sub", text: product.why_not }));
}

function productStorageTables(tables, saved = false) {
  if (!tables) return null;
  const written = tables.written || [], skipped = tables.skipped || [];
  if (!written.length && !skipped.length && !tables.error) return null;
  return el("div", {}, written.length ? el("div", {},
    el("h3", { text: saved ? "Availability tables updated" : "Availability tables to update" }),
    el("ul", {}, written.map(deck => el("li", { text: deck.title || deck.id })))) : null,
  skipped.length ? el("div", {}, el("h3", { text: "Tables needing attention" }),
    el("ul", {}, skipped.map(deck => el("li", { text: `${deck.title || deck.id}: ${deck.why}` })))) : null,
  tables.error ? el("p", { class: "form-error", text: tables.error }) : null,
  skipped.length || tables.error ? el("a", { href: TABLES_HREF, text: "Tables out of date" }) : null);
}

/** A preview never changes storage. The final explicit action applies its opaque review token. */
function openProductStorage(ctx, intact) {
  if (!productStorageHere(ctx) || ctx.busy || !ctx.product?.can_change || !mayDo("products")) return null;
  ctx.busy = true; drawProductStorage(ctx);
  const sheet = openSheet(intact === "yes" ? "Keep product intact" : "Break product up", { onClose: () => {
    productStorageSheets.delete(sheet);
    ctx.busy = false;
    if (productStorageHere(ctx)) drawProductStorage(ctx);
    if (review.saved) setTimeout(() => { if (productStorageHere(ctx)) route(); }, 0);
  } });
  const review = { saved: false, sending: false, stale: false, failed: false };
  productStorageSheets.add(sheet);
  const here = () => !sheet.closed && productStorageHere(ctx);
  const error = el("p", { class: "form-error", role: "alert" });
  let preview = null;
  function actions() {
    sheetActions(sheet, [review.stale ? { text: "Refresh product", kind: "primary", onclick: () => {
      if (!here()) return;
      sheet.close(); ctx.refresh();
    } } : review.failed ? { text: "Try again", kind: "primary", onclick: () => { if (here() && review.failed) check(); } }
      : preview?.ready ? { text: intact === "yes" ? "Keep intact" : "Break up", kind: "primary",
      disabled: review.sending, onclick: apply } : null,
    { text: preview?.ready ? "Cancel" : "Close", disabled: review.sending, onclick: () => sheet.close() }]);
  }
  async function apply() {
    if (!here() || review.sending || review.saved || review.stale || !preview?.ready) return;
    review.sending = true; error.textContent = ""; actions();
    try {
      const answer = await apiWrite("/api/product/intact/apply", { preview: preview.preview });
      state.library = null;
      if (!here()) return;
      review.saved = true;
      clear(sheet.body);
      add(sheet.body, [el("p", { text: `${answer.name || ctx.product.name} ${answer.intact === "yes"
        ? "is now kept intact." : "is now broken up into storage."}` }),
      warningsBox(answer.warnings || [], "Saved, with notes"), productStorageTables(answer.tables, true)]);
      sheetActions(sheet, [{ text: "Done", kind: "primary", onclick: () => sheet.close() }]);
    } catch (failure) {
      if (!here()) return;
      review.stale = failure.status === 409;
      error.textContent = failure.message;
    } finally {
      review.sending = false;
      if (here() && !review.saved) actions();
    }
  }
  /** The preview: a stale product (409) is refreshed on the page; any other failure can simply be checked again. */
  async function check() {
    review.failed = false; error.textContent = "";
    clear(sheet.body).append(loadingBox("Checking the storage change…", { small: true })); actions();
    try {
      preview = await apiWrite("/api/product/intact/preview", { stem: ctx.stem, intact,
        fingerprint: ctx.product.fingerprint });
      if (!here()) return;
      clear(sheet.body);
      add(sheet.body, [el("p", { text: ctx.product.name }),
        el("p", { text: !preview.ready ? preview.reason || "This change cannot be made yet."
          : intact === "yes" ? "Keep this product's decks together. Its cards will count as in use for other decks."
            : "Return this product's cards to storage so they are free for other decks." }),
        preview.kit_cleared ? el("p", { text: "Its sleeves and deck box records will be cleared." }) : null,
        warningsBox(preview.warnings || [], "Check this change"), productStorageTables(preview.tables), error]);
      actions();
    } catch (failure) {
      if (!here()) return;
      review.stale = failure.status === 409;
      review.failed = !review.stale;
      clear(sheet.body).append(error); error.textContent = failure.message; actions();
    }
  }
  check();
  return sheet;
}
