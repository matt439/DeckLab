/* One reviewed plan for built decks and whole intact products; all writes use its exact digest. */
"use strict";

const tokenPlanSheets = new Set();

function closeTokenPlanSheets() {
  for (const sheet of [...tokenPlanSheets]) { sheet.tokenPlanContext.abandoned = true; sheet.close(); }
}

function tokPlanOwner(ctx) {
  const view = ctx.view;
  return !ctx.abandoned && tokensActive(view) && view.planContext === ctx && ctx.hash === location.hash
    && ctx.token === routeToken && ctx.profile === state.profile?.id && ctx.root === view.root
    && ctx.data === view.data && ctx.dataSha === view.data.sha256 && ctx.seq === view.seq && ctx.space === view.space
    && view.canEdit && canEditSpace(view.space);
}

/** Validate the preview's participant/count contract before offering a write or claiming an empty plan. */
function tokPlanEvidence(plan, space) {
  const named = text => typeof text === "string" && text.trim() && !/[\u0000-\u001f\u007f]/.test(text);
  const count = value => Number.isSafeInteger(value) && value >= 0;
  const strings = items => Array.isArray(items) && items.every(named);
  const list = items => Array.isArray(items) && items.length <= 2000;
  const detail = item => item && named(item.title) && typeof item.changed === "boolean" && typeof item.editable === "boolean"
    && typeof item.after === "string" && list(item.lines) && item.lines.every(line => line && named(line.text)
      && (line.sides === undefined || strings(line.sides)));
  const demands = item => item && named(item.id) && named(item.title) && count(item.spares) && strings(item.short)
    && list(item.packs) && item.packs.every(pack => pack && named(pack.token) && named(pack.card));
  if (!plan || typeof plan !== "object" || typeof plan.sha256 !== "string" || !/^[a-f0-9]{64}$/.test(plan.sha256)
      || (plan.space === undefined ? space !== HOME_SPACE : plan.space !== space)
      || !list(plan.decks) || !count(plan.changes) || !strings(plan.warnings || [])) return null;
  const products = plan.products === undefined ? [] : plan.products;
  if (!list(products) || !count(plan.product_changes === undefined ? 0 : plan.product_changes)) return null;
  const ids = new Set(), stems = new Set(), holders = new Set();
  for (const deck of plan.decks) {
    if (!detail(deck) || !demands(deck) || !(deck.before === null || typeof deck.before === "string") || ids.has(deck.id)) return null;
    ids.add(deck.id);
  }
  for (const product of products) {
    if (space !== HOME_SPACE || !detail(product) || typeof product.before !== "string" || !named(product.holder)
        || typeof product.stem !== "string" || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(product.stem) || product.stem === "status"
        || stems.has(product.stem) || holders.has(product.holder) || !(product.link === null || named(product.link))
        || !list(product.decks) || !product.decks.length) return null;
    stems.add(product.stem); holders.add(product.holder);
    for (const deck of product.decks) {
      if (!demands(deck) || ids.has(deck.id)) return null;
      ids.add(deck.id);
    }
  }
  const decks = plan.decks.filter(item => item.changed), changedProducts = products.filter(item => item.changed);
  if (plan.changes !== decks.length || (plan.product_changes ?? 0) !== changedProducts.length) return null;
  return { products, decks, changedProducts, blocked: [...decks, ...changedProducts].filter(item => !item.editable) };
}

function tokPlanDemands(deck, product = false) {
  const verdict = { check: " (details not recorded)", differs: " (a stand-in: tell your opponent)" };
  return el("div", {},
    deck.packs.length ? el("ul", { class: "pack-plain" }, deck.packs.map(pack => el("li", {
      text: pack.token + ": " + pack.card + (verdict[pack.verdict] || "") }))) : null,
    deck.spares ? el("p", { class: "sub", text: plural(deck.spares, "spare card") + (product
      ? " allocated within the whole product" : " shared out to it") }) : null,
    deck.short.length ? el("p", { class: "box box-warn", text: "No card left for " + deck.short.join(", ") }) : null);
}

/** Ordinary built decks retain their existing line and per-deck face/sleeve guidance. */
function tokPlanDeck(deck) {
  const lines = deck.lines.map(line => line.text + (line.sides?.length ? " (" + line.sides.join("; ") + ")" : ""));
  return el("li", { class: "tok-plan-deck" + (deck.changed ? " tok-plan-changed" : "") },
    el("p", {}, el("b", { text: deck.title }), deck.changed ? null : el("span", { class: "sub", text: " (no change)" })),
    el("p", { text: "Packs: " + (lines.length ? lines.join("; ") : "no token cards") }),
    deck.changed ? el("p", { class: "sub", text: "Now: " + (deck.before === null ? "not recorded" : deck.before || "no token cards") }) : null,
    tokPlanDemands(deck));
}

/** Product lines count physical cards for the whole box; its actual decks show demands, not extra copies. */
function tokPlanProduct(product) {
  return el("li", { class: "tok-plan-deck tok-plan-product" + (product.changed ? " tok-plan-changed" : "") },
    el("p", {}, el("a", { href: product.link === null ? "#/library?format=product" : deckHref(product.link), text: product.title }),
      product.changed ? null : el("span", { class: "sub", text: " (no change)" })),
    el("p", { text: "Whole product packs: " + (product.lines.length ? product.lines.map(line => line.text).join("; ")
      : "quantities not recorded (unknown)") }),
    el("p", { class: "sub", text: "Now: " + (product.before || "quantities not recorded (unknown)") }),
    el("p", { class: "sub", text: "One physical record covers the whole box. These decks draw from it; a paired card counts once." }),
    el("ul", { class: "pack-plain" }, product.decks.map(deck => el("li", {}, el("p", {}, el("b", { text: deck.title })),
      tokPlanDemands(deck, true)))));
}

function tokPlanReceipt(answer, evidence) {
  const same = (actual, expected) => Array.isArray(actual) && actual.length === expected.length && new Set(actual).size === actual.length
    && actual.every(id => expected.includes(id));
  if (!answer || answer.saved !== evidence.decks.length || !same(answer.decks, evidence.decks.map(item => item.id))) return false;
  const products = evidence.changedProducts.map(item => item.stem);
  return products.length ? answer.saved_products === products.length && same(answer.products, products)
    : (answer.saved_products === undefined || answer.saved_products === 0) && (answer.products === undefined || same(answer.products, []));
}

/** A closed review may refresh only its original Tokens page, after the sheet's temporary Back entry lands. */
function tokPlanAfterClose(ctx) {
  if (ctx.pending || ctx.refreshed || !tokPlanOwner(ctx)) return;
  if (!ctx.confirmed && !ctx.needsRefresh) { ctx.view.planContext = null; return; }
  const entry = ctx.sheet.entry;
  const stop = () => { window.removeEventListener("popstate", landed); window.removeEventListener("hashchange", stop); };
  const landed = () => {
    stop();
    if (!ctx.refreshed && tokPlanOwner(ctx) && (!entry || history.state?.sheet !== entry.token
        && history.state?.pos === entry.pos - 1)) {
      ctx.refreshed = true; ctx.view.planContext = null; refreshTokens(ctx.view);
    }
  };
  if (!entry || entry.fromHistory || history.state?.sheet !== entry.token) landed();
  else { window.addEventListener("popstate", landed); window.addEventListener("hashchange", stop); }
}

function openTokenPlan(view) {
  if (!tokensActive(view) || view.busy || !view.canEdit || !canEditSpace(view.space)
      || view.planContext || document.querySelector("dialog[open]")) return null;
  const ctx = { view, data: view.data, dataSha: view.data.sha256, seq: view.seq, space: view.space, hash: location.hash,
    token: routeToken, profile: state.profile?.id, root: view.root,
    pending: false, confirmed: false, needsRefresh: false, refreshed: false, request: 0, plan: null };
  view.planContext = ctx;
  const sheet = ctx.sheet = openSheet("Plan packed token cards", { wide: true, onClose: () => {
    tokenPlanSheets.delete(sheet); tokPlanAfterClose(ctx);
  } });
  sheet.tokenPlanContext = ctx;
  tokenPlanSheets.add(sheet);
  ctx.current = () => !sheet.closed && tokPlanOwner(ctx);
  ctx.here = () => ctx.current() && [...document.querySelectorAll("dialog[open]")].at(-1) === sheet.dialog;
  const path = "/api/tokens/plan" + (view.space !== HOME_SPACE ? "?space=" + encodeURIComponent(view.space) : "");
  ctx.load = async event => {
    if (!ctx.here() || ctx.pending || view.busy || event && (!event.currentTarget?.isConnected
        || !sheet.foot.contains(event.currentTarget))) return;
    const request = ++ctx.request;
    ctx.plan = null;
    clear(sheet.body).append(loadingBox("Working out the plan…"));
    sheetActions(sheet, [{ text: "Cancel", onclick: () => sheet.close() }]);
    try {
      const plan = await api(path);
      if (!ctx.current() || request !== ctx.request) return;
      if (!tokPlanEvidence(plan, view.space)) throw new Error("The plan's quantities or participants could not be checked.");
      ctx.needsRefresh = false; ctx.plan = plan;
      tokPlanShow(view, sheet, plan, ctx.load);
    } catch (failure) {
      if (!ctx.current() || request !== ctx.request) return;
      clear(sheet.body).append(errorBox("The plan couldn't be worked out", failure, null));
      sheetActions(sheet, [{ text: "Cancel", onclick: () => sheet.close() },
        { text: "Reload plan", kind: "primary", onclick: ctx.load }]);
    }
  };
  ctx.load();
  return sheet;
}

function tokPlanShow(view, sheet, plan, reload) {
  const ctx = view.planContext, evidence = tokPlanEvidence(plan, view.space);
  if (!ctx || ctx.sheet !== sheet || ctx.plan !== plan || !ctx.current() || !evidence) return;
  const signature = JSON.stringify(plan), decks = plan.decks, products = evidence.products;
  const words = [evidence.decks.length ? plural(evidence.decks.length, "deck") : "",
    evidence.changedProducts.length ? plural(evidence.changedProducts.length, "product") : ""].filter(Boolean).join(" and ");
  const blocked = () => evidence.blocked.length || evidence.changedProducts.length && !mayDo("products");
  clear(sheet.body).append(
    el("p", { class: "sub", text: "One card for each token every built deck or intact product's deck makes, chosen together so your cards go as far as they can, then spare cards shared out. "
      + "The whole-product totals count physical cards. Check paired-card faces before sleeving." }),
    decks.length ? el("ul", { class: "pack-plain tok-plan" }, decks.map(tokPlanDeck)) : "",
    products.length ? el("ul", { class: "pack-plain tok-plan", "aria-label": "Whole intact products" }, products.map(tokPlanProduct)) : "",
    !decks.length && !products.length ? emptyBox("There are no built decks or intact products to plan for.") : "",
    warningsBox(plan.warnings || [], "Worth checking") || "",
    evidence.blocked.length ? el("p", { class: "box box-warn", text: "You can't change " + evidence.blocked.map(item => item.title).join(" and ")
      + ", so the plan can't be applied." }) : "");
  const message = el("p", { class: "box box-crit", role: "alert", tabindex: "-1", hidden: true });
  sheet.body.append(message);
  // With nothing to plan for, Close is the only way on (no disabled Apply).
  const actions = () => sheetActions(sheet, !decks.length && !products.length && !ctx.needsRefresh
    ? [{ text: "Close", onclick: () => sheet.close() }] : ctx.needsRefresh ? [{ text: "Cancel", onclick: () => sheet.close() },
    { text: "Reload plan", kind: "primary", onclick: reload }] : [{ text: "Cancel", disabled: ctx.pending, onclick: () => sheet.close() },
    { text: ctx.pending ? "Applying…" : words ? "Apply to " + words : "Nothing to change", kind: "primary", value: "apply",
      disabled: ctx.pending || !words || Boolean(blocked()), onclick: apply }]);
  async function apply(event) {
    if (!ctx.here() || !event?.currentTarget?.isConnected || !sheet.foot.contains(event.currentTarget)
        || view.busy || ctx.pending || ctx.confirmed || ctx.needsRefresh || ctx.plan !== plan
        || JSON.stringify(plan) !== signature || !words || blocked()) return;
    const trigger = document.activeElement;
    const focusOwned = () => document.activeElement === trigger || document.activeElement === document.body || !document.activeElement?.isConnected;
    ctx.pending = true; message.hidden = true; setTokensBusy(view, true); actions();
    try {
      const answer = await apiWrite("/api/tokens/plan", tokBody(view, { sha256: plan.sha256 }));
      if (!tokPlanReceipt(answer, evidence)) throw new Error("The save result could not be confirmed.");
      state.library = null;
      if (!tokPlanOwner(ctx)) return;
      ctx.confirmed = true;
      if (ctx.here()) { toast("Packed token cards saved for " + words); sheet.close(); }
      else if (ctx.current()) {
        clear(sheet.body).append(el("p", { role: "status", text: "Packed token cards saved for " + words + "." }));
        sheetActions(sheet, [{ text: "Done", kind: "primary", onclick: () => { if (ctx.here()) sheet.close(); } }]);
      }
    } catch (failure) {
      state.library = null;
      if (!tokPlanOwner(ctx)) return;
      ctx.needsRefresh = true;
      if (ctx.current()) {
        message.textContent = (failure.status ? failure.message : "The save result could not be confirmed.")
          + " Reload the plan and review it before applying again.";
        message.hidden = false; actions();
        if (ctx.here() && focusOwned()) message.focus();
      }
    } finally {
      ctx.pending = false;
      if (tokPlanOwner(ctx)) {
        setTokensBusy(view, false);
        if (sheet.closed) tokPlanAfterClose(ctx);
      }
    }
  }
  actions();
}
