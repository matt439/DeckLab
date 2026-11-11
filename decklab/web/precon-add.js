/* "Add a precon" on the Collection page (lib/api/precons.py): find a published precon (MTGJSON's lists),
 * preview its cards, then add them to the space's collection and make its built deck in one save. Opened
 * from collection.js's head; reads collection.js, collection-filing.js and precon-token-choices.js globals
 * at call time. */
"use strict";

const PRECON_SEARCH_MS = 250;       // wait this long after typing before searching

/** "Add a precon": find a published precon (MTGJSON's lists), see its cards, then add them to this
 * collection and make its built deck, in one save (lib/api/precons.py). */
function openPreconSheet(cv) {
  if (!colActive(cv) || cv.busy || !cv.editable) return null;
  const whose = colWhose(cv.space);
  const sheet = colOpenSheet(`Add a precon to ${whose}`, { wide: true, onClose: () => {
    clearTimeout(ctx.timer);
    if (ctx.dropReceipt && colActive(cv)) colReload(cv, ctx.dropReceipt.words, ctx.dropReceipt.stale, ctx.dropReceipt.filing);
  } });
  const ctx = { cv, sheet, whose, seq: 0, busy: false, preview: null, timer: null };
  const input = el("input", { id: `precon-q-${sheet.heading.id}`, type: "search", autocomplete: "off",
    placeholder: "Deck or set name" });
  ctx.query = input;
  ctx.message = el("div", { class: "col-sheet-message", role: "status", "aria-live": "polite" });
  ctx.area = el("div", { class: "precon-area" });
  ctx.back = { text: "← Back to the list", value: "back", onclick: () => backToPrecons(ctx) };
  input.addEventListener("input", () => {
    clearTimeout(ctx.timer);
    ctx.timer = setTimeout(() => searchPrecons(ctx), PRECON_SEARCH_MS);
  });
  ctx.searchField = el("div", { class: "precon-search-area" },
    el("p", { class: "sub", text: "A precon's cards go into the collection and its list becomes a built deck, in one go. Secret Lair drops add cards only, without a deck."
      + (cv.space === HOME_SPACE ? ` A product bought through a recorded order arrives through ${routeFor("shopping").label} (${routeFor("receipt").label}) instead.` : "") }),
    el("label", { class: "field precon-search", for: input.id }, el("span", { class: "sr-only", text: "Find a precon" }), input));
  add(sheet.body, [ctx.searchField, ctx.message, ctx.area]);
  sheetActions(sheet, [{ text: "Cancel", value: "cancel", onclick: () => sheet.close() }]);
  searchPrecons(ctx);
  input.focus();
  return ctx;
}

function backToPrecons(ctx) {
  clearTimeout(ctx.timer);
  ctx.preview = null;
  ctx.searchField.hidden = false;
  ctx.sheet.heading.textContent = `Add a precon to ${ctx.whose}`;
  sheetActions(ctx.sheet, [{ text: "Cancel", value: "cancel", onclick: () => ctx.sheet.close() }]);
  searchPrecons(ctx);
  ctx.query.focus();
}

/** Whether a deck's source is a page on Wizards' own site (lib/precons.py, from_wizards). */
function fromWizards(source) {
  try { return /(^|\.)wizards\.com$/i.test(new URL(source).hostname); } catch (e) { return false; }
}

async function searchPrecons(ctx) {
  if (ctx.sheet.closed || ctx.preview || ctx.searchField.hidden) return;   // a search typed just before a pick
  const seq = ++ctx.seq;
  const q = ctx.query.value.trim();
  clear(ctx.message).append(loadingBox("Finding precons…"));
  try {
    const answer = await api(`/api/precons?${new URLSearchParams({ q, products: "1" })}`);
    if (seq !== ctx.seq || ctx.sheet.closed) return;
    clear(ctx.message);
    const decks = answer.decks || [];
    add(clear(ctx.area), [
      decks.length ? el("ul", { class: "precon-list" }, decks.map((d) => el("li", {},
        el("button", { type: "button", class: "precon-pick", onclick: () => previewPrecon(ctx, d) },
          el("span", { class: "precon-pick-words" }, el("strong", { text: d.name }),
            el("small", { text: [d.set_name || d.code.toUpperCase(), d.type, d.type === "Secret Lair Drop" ? "Cards only" : null].filter(Boolean).join(" · ") })),
          d.released ? el("small", { class: "precon-pick-date", text: String(d.released).slice(0, 4) }) : null))))
        : emptyBox(q
          ? "No precon matches that. Only decks whose list has been published are here."
          : "No precons are listed.", null, { live: !!q }),
      answer.more ? el("p", { class: "result-count", text: "More match: type more of the name to narrow the list." }) : null,
      el("p", { class: "result-count", text: `Lists from MTGJSON${answer.date ? ` (updated ${answer.date})` : ""}, most from Wizards' published lists.` })]);
  } catch (error) {
    if (seq !== ctx.seq || ctx.sheet.closed) return;
    clear(ctx.message).append(loadFailed("The list of precons", error, () => searchPrecons(ctx)));
  }
}

async function previewPrecon(ctx, deck, keptTitle = null) {
  const cv = ctx.cv;
  clearTimeout(ctx.timer);            // a search typed just before the pick would cover the preview
  const seq = ++ctx.seq;
  ctx.preview = null;
  clear(ctx.area);
  ctx.searchField.hidden = true;
  ctx.sheet.heading.textContent = deck.name;
  clear(ctx.message).append(loadingBox(`Reading ${deck.name}…`));
  sheetActions(ctx.sheet, [ctx.back]);
  try {
    const params = new URLSearchParams({ file: deck.file });
    if (cv.space !== HOME_SPACE) params.set("space", cv.space);
    const preview = await api(`/api/precons/preview?${params}`);
    if (seq !== ctx.seq || ctx.sheet.closed || !colActive(cv)) return;
    ctx.preview = preview;
    ctx.keptTitle = keptTitle;
    clear(ctx.message);
    drawPreconPreview(ctx);
  } catch (error) {
    if (seq !== ctx.seq || ctx.sheet.closed || !colActive(cv)) return;
    clear(ctx.message).append(loadFailed(deck.name, error, () => previewPrecon(ctx, deck, keptTitle)));
  }
}

/** One card of a precon's list, as the deck's text writes it. */
function preconLine(c) {
  const finish = c.finish === "foil" ? " *F*" : c.finish === "etched" ? " *E*" : "";
  return `${c.qty} ${c.name}${c.set ? ` (${c.set.toUpperCase()}) ${c.number}${finish}` : ""}`;
}

/** Source receipts and choices belong to the current preview, person and connected sheet. */
function preconBonusOwner(ctx, choice) {
  return choice && !ctx.sheet.closed && !ctx.tokenPreviewStale && colActive(ctx.cv) && ctx.bonusChoice === choice
    && ctx.preview === choice.preview && ctx.seq === choice.seq && state.profile?.id === choice.profile
    && routeToken === choice.token && location.hash === choice.hash && ctx.cv.root === choice.root
    && JSON.stringify(choice.preview.bonus_import) === choice.signature && ctx.area.isConnected
    && (!choice.section || choice.section.isConnected && ctx.area.contains(choice.section))
    && choice.options.every(row => row.node.isConnected && row.node.parentNode === row.label && choice.section.contains(row.label));
}

function preconBonusChoice(ctx) {
  ctx.bonusChoice = null; ctx.bonusMalformed = false;
  const p = ctx.preview, offer = p.bonus_import;
  if (!offer) return null; // Compatibility with a page fixture or an older server without the feature.
  if (typeof offer.source_sha256 !== "string" || !/^[a-f0-9]{64}$/.test(offer.source_sha256)
      || !Array.isArray(offer.rows) || offer.rows.length > 250
      || new Set(offer.rows.map(row => row?.source_row)).size !== offer.rows.length
      || !offer.rows.every(row => row && Number.isSafeInteger(row.source_row) && row.source_row > 0
        && typeof row.words === "string" && row.words.length && Number.isSafeInteger(row.qty) && row.qty > 0 && row.qty <= 250
        && Number.isSafeInteger(row.owned) && row.owned >= 0 && typeof row.selected === "boolean"
        && (row.problem === null || typeof row.problem === "string") && !(row.problem && row.selected))) {
    ctx.bonusMalformed = true;
    return el("p", { class: "box box-warn", text: "The bonus cards could not be checked. Preview this precon again before adding it." });
  }
  const choice = ctx.bonusChoice = { preview: p, offer, signature: JSON.stringify(offer), options: [],
    seq: ctx.seq, token: routeToken, hash: location.hash, root: ctx.cv.root, profile: state.profile?.id, section: null };
  if (!offer.rows.length) return null;
  const baseCards = p.adds.cards - offer.rows.filter(row => row.selected).reduce((sum, row) => sum + row.qty, 0);
  const section = choice.section = el("section", { class: "precon-section precon-bonus" },
    el("h3", { text: "Fixed bonus cards" }),
    el("p", { class: "sub", text: "Check the box's contents. Selected cards go into the collection only, never the deck list." }));
  for (const row of offer.rows) {
    const node = el("input", { type: "checkbox" });
    node.checked = row.selected; node.disabled = Boolean(row.problem) || !p.editable;
    const label = el("label", { class: "choice" }, node, el("span", { text: `${row.qty} ${row.words}`
      + (row.owned ? ` · ${row.owned} already owned` : "") }));
    const option = { node, label, row, accepted: row.selected }; choice.options.push(option);
    node.addEventListener("change", () => {
      if (ctx.busy || !preconBonusOwner(ctx, choice) || node.disabled
          || [...document.querySelectorAll("dialog[open]")].at(-1) !== ctx.sheet.dialog) { node.checked = option.accepted; return; }
      option.accepted = Boolean(node.checked);
      ctx.addSummary.textContent = `${plural(baseCards + choice.options.filter(item => item.accepted).reduce((sum, item) => sum + item.row.qty, 0), "card")} go into ${ctx.whose}`;
    });
    section.append(label);
    if (row.problem) section.append(el("p", { class: "field-problem", text: row.problem }));
  }
  return section;
}

function drawPreconPreview(ctx) {
  const p = ctx.preview;
  const d = p.deck;
  const counts = p.counts || {};
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  const leftOut = Object.entries(p.left_out || {}).map(([what, n]) => plural(n, what));
  const adds = p.adds || { rows: 0, cards: 0 };
  const titleInput = el("input", { id: `precon-title-${ctx.sheet.heading.id}`, type: "text", maxlength: "100", value: ctx.keptTitle ?? p.title });
  ctx.keptTitle = null;
  ctx.titleInput = titleInput;
  ctx.titleNote = el("p", { class: "field-problem precon-title-note", role: "status" });
  const sayTaken = () => {
    ctx.titleNote.textContent = p.exists && titleInput.value.trim() === p.title
      ? `There's already a deck with this title (${p.exists}): pick another.` : "";
  };
  titleInput.addEventListener("input", sayTaken);
  sayTaken();
  const lists = p.lists || {};
  const tile = (c, section) => cardTile(c.card || null, { qty: c.qty, name: c.name,
    meta: c.set ? `${c.set.toUpperCase()} ${c.number}` : "Any printing", finish: c.finish,
    viewerGroup: "precon", caption: `${section === "Deck" ? "" : `${section} · `}${preconLine(c)}` });
  clear(ctx.area);
  ctx.addSummary = el("b", { text: `${plural(adds.cards || 0, "card")} go into ${ctx.whose}` });
  add(ctx.area, [
    el("p", { class: "sub precon-meta" }, [d.set_name || d.code.toUpperCase(), d.type, d.released ? `released ${d.released}` : null].filter(Boolean).join(" · "),
      d.source ? [" · ", el("a", { href: d.source, target: "_blank", rel: "noopener noreferrer",
        text: fromWizards(d.source) ? "Wizards' list" : "Where the list is from" })] : null),
    el("p", { class: "precon-summary" }, `${p.cards_only ? "Cards only; no deck is created" : p.kind === "commander" ? "Commander deck" : "60-card deck"} · ${plural(total, "card")}. `,
      ctx.addSummary,
      p.dropped_basics ? ` (plain basic lands left out)` : "", "."),
    p.problems && p.problems.length ? el("div", { class: "box box-warn" },
      el("h3", { text: "It can't be added yet" }),
      el("p", { text: "Deck Lab can't match these cards to Scryfall's data, usually because the set is too new. Try again once the card data has caught up (it updates weekly)." }),
      el("ul", {}, p.problems.slice(0, 20).map((x) => el("li", { text: x.message })))) : null,
    p.deck_problems && p.deck_problems.length ? el("div", { class: "box box-warn" },
      el("h3", { text: "Its list can't be made into a deck" }),
      el("ul", {}, p.deck_problems.slice(0, 20).map((x) => el("li", { text: x.message })))) : null,
    p.cards_only ? null : el("label", { class: "field precon-title", for: titleInput.id }, el("span", { text: "Deck title" }), titleInput),
    p.cards_only ? null : ctx.titleNote,
    leftOut.length || (p.tokens && p.tokens.length) ? el("p", { class: "sub" },
      leftOut.length ? `Not added: ${leftOut.join(", ")}. ` : "",
      !p.token_import && p.tokens && p.tokens.length ? ["Its token cards (", p.tokens.map((t) => `${t.count} ${t.name}`).join(", "),
        ") aren't added: record them on the ", el("a", { href: "#/tokens", text: "Tokens page" }), " once checked."] : null) : null,
    (p.notes || []).length ? el("p", { class: "sub precon-notes" }, p.notes.join(" ")) : null,
    preconTokenChoice(ctx),
    preconBonusChoice(ctx),
    Object.entries(lists).map(([section, lines]) => el("section", { class: "precon-section" },
      el("h3", { text: `${section === "Deck" ? p.cards_only ? "Cards" : "Deck" : section} (${num(counts[section] || 0)})` }),
      el("div", { class: "card-tiles precon-tiles" }, lines.map((c) => tile(c, section)))))]);
  if (!p.editable) ctx.area.append(el("p", { class: "box box-info", text: p.cards_only ? "You can't add cards here." : "You can't add cards and decks here." }));
  sheetActions(ctx.sheet, [ctx.back,
    p.ready && p.editable && !ctx.bonusMalformed ? { text: `Add ${d.name}`, kind: "primary", value: "add", onclick: event => {
      if (preconAddHere(ctx, p, event.currentTarget)) addPrecon(ctx);
    } } : null]);
}

function preconAddHere(ctx, preview, button) {
  return ctx.preview === preview && !ctx.sheet.closed && button?.isConnected && ctx.sheet.foot.contains(button)
    && [...document.querySelectorAll("dialog[open]")].at(-1) === ctx.sheet.dialog;
}

async function addPrecon(ctx) {
  const cv = ctx.cv;
  const p = ctx.preview;
  if (ctx.busy || ctx.sheet.closed || !p || !p.ready || !p.editable || !cv.editable || !canEditSpace(cv.space)
      || !colActive(cv) || ctx.tokenPreviewStale || ctx.bonusMalformed) return;
  const bonusReview = ctx.bonusChoice;
  if (bonusReview && (!preconBonusOwner(ctx, bonusReview)
      || [...document.querySelectorAll("dialog[open]")].at(-1) !== ctx.sheet.dialog
      || bonusReview.options.some(row => row.node.checked !== row.accepted))) return;
  const bonus = bonusReview ? { bonus_source_sha256: bonusReview.offer.source_sha256,
    bonus_choices: bonusReview.options.filter(row => row.accepted).map(row => row.row.source_row) } : {};
  const tokensChosen = ctx.tokenChoice?.node.checked === true;
  const tokenReview = ctx.tokenChoice, tokenSelection = tokensChosen ? preconTokenSelection(ctx) : null;
  if (tokensChosen && !tokenSelection) return;
  const requestHash = location.hash;
  const title = ctx.titleInput.value.trim();
  if (!title && !p.cards_only) { ctx.titleNote.textContent = "The deck needs a title."; ctx.titleInput.focus(); return; }
  ctx.busy = true;
  preconTokensBusy(ctx, true);
  for (const row of bonusReview?.options || []) row.node.disabled = true;
  for (const button of ctx.sheet.foot.querySelectorAll("button")) button.disabled = true;
  clear(ctx.message).append(loadingBox(`Adding ${p.deck.name}…`));
  try {
    const answer = await apiWrite("/api/precons/add", { space: cv.space, file: p.deck.file, title, sha256: p.sha256,
      ...bonus,
      ...(tokensChosen ? { add_tokens: true, tokens_sha256: tokenSelection.offer.sha256,
        tokens_source_sha256: tokenSelection.offer.source_sha256,
        ...(tokenSelection.choices ? { tokens_choices: tokenSelection.choices } : {}) } : {}) });
    cv.rows = null;
    invalidateLibrary(); // The confirmed write stands even if its review is no longer the current UI.
    if (ctx.sheet.closed || !colActive(cv) || ctx.preview !== p || requestHash !== location.hash
        || tokensChosen && !preconTokenOwner(ctx, tokenReview) || bonusReview && !preconBonusOwner(ctx, bonusReview)) return;
    const added = answer.collection && answer.collection.added;
    const tokenCount = tokensChosen && answer.tokens?.cards === tokenSelection.cards && answer.tokens?.rows === tokenSelection.rows
      ? tokenSelection.cards : null;
    if (p.cards_only) {
      if (answer.cards_only !== true || answer.deck !== null) throw Error("The cards-only result could not be confirmed. Check the collection before adding again.");
      const words = `${Number.isSafeInteger(added?.cards) ? plural(added.cards, "card") : "Cards"} from ${p.deck.name} added to ${ctx.whose}. No deck was created.`;
      const filing = colFilingSnapshot(answer.collection, cv);
      ctx.dropReceipt = { words, stale: answer.stale_tables, filing };
      ctx.preview = null;
      ctx.sheet.heading.textContent = `${p.deck.name} is added`;
      clear(ctx.message).append(el("div", { class: "box box-good", role: "status", text: words }));
      const receiptCv = { ...cv, message: ctx.area };
      clear(ctx.area);
      if (tokensChosen) ctx.area.append(el("p", { class: tokenCount === null ? "box box-warn" : "sub", text: tokenCount === null
        ? "The token addition count was not confirmed. Check the Tokens page before adding any again."
        : `${plural(tokenCount, "token card")} also added as unconfirmed rows. Check their printings and reverse faces on the Tokens page.` }));
      if (filing) add(ctx.area, [colFilingGuide(receiptCv, filing)]);
      if (answer.stale_tables?.length) add(ctx.area, [staleTablesPart(answer.stale_tables)]);
      if (answer.trials?.length) add(ctx.area, [ptrTrialsPart(answer.trials)]);
      sheetActions(ctx.sheet, [{ text: "Close", kind: "primary", onclick: () => ctx.sheet.close() }]);
      return;
    }
    ctx.sheet.close();
    // The deck page's box about a new deck (editor-deckpage.js, savedBox), as the editor's Create leaves it:
    // warnings (no sleeves yet, the deck rules) and other decks' tables now out of date.
    const hash = deckHref(answer.deck.id, "target");
    const filing = colFilingSnapshot(answer.collection, cv, "precon");
    state.saved = { hash, profile: state.profile?.id, version: "target", mode: "new", answer: { ...answer.deck,
      precon: { name: p.deck.name, whose: ctx.whose, cards: added ? added.cards : 0,
        ...(filing ? { filing } : {}), ...(answer.trials?.length ? { trials: answer.trials } : {}),
        ...(tokensChosen ? { tokens: tokenCount, tokens_uncertain: tokenCount === null } : {}) } } };
    state.scroll.delete(hash);        // open the deck at the top, where the box is
    toast("");                        // an older note would cover the box
    location.hash = hash;
  } catch (error) {
    if (error.status >= 500 || !error.data) { cv.rows = null; invalidateLibrary(); }
    if (ctx.sheet.closed || !colActive(cv) || ctx.preview !== p || requestHash !== location.hash
        || tokensChosen && !preconTokenOwner(ctx, tokenReview) || bonusReview && !preconBonusOwner(ctx, bonusReview)) return;
    ctx.busy = false;
    preconTokensBusy(ctx, false);
    for (const row of bonusReview?.options || []) row.node.disabled = Boolean(row.row.problem);
    for (const button of ctx.sheet.foot.querySelectorAll("button")) button.disabled = false;
    const data = error.data || {};
    if (error.status >= 500 || !error.data) {
      // No answer of Deck Lab's own (no connection, a proxy's error page), or an unexpected failure: the
      // save may have gone in, and adding again would add the cards twice.
      cv.rows = null;
      invalidateLibrary();
      ctx.tokenPreviewStale = true;
      preconTokensBusy(ctx, true);
      for (const row of bonusReview?.options || []) row.node.disabled = true;
      clear(ctx.message).append(el("div", { class: "box box-crit", role: "alert" }, el("p", { text: error.message }),
        el("p", { text: `It isn't known whether its cards went into ${ctx.whose}. Look there${p.cards_only
          ? tokensChosen ? " and on the Tokens page" : "" : ` (and on the Decks page${tokensChosen ? " and Tokens page" : ""})`} before adding it again.` })));
      sheetActions(ctx.sheet, [{ text: "Close", kind: "primary", value: "close",
        onclick: () => { ctx.sheet.close(); if (colActive(cv)) colReload(cv, error.message); } }]);
      return;
    }
    if (error.status === 409 && (data.token_conflict || data.bonus_conflict || (tokensChosen || bonusReview) && data.sha256)) {
      ctx.tokenPreviewStale = true;
      preconTokensBusy(ctx, true);
      for (const row of bonusReview?.options || []) row.node.disabled = true;
      clear(ctx.message).append(el("div", { class: "box box-warn", role: "alert" }, el("p", { text: error.message }),
        el("p", { text: bonusReview ? "Nothing was added. Preview again to review the current collection and bonus cards before choosing what to add."
          : "Nothing was added. Preview again to review the current collection and token list, then choose whether to add the token cards." })));
      sheetActions(ctx.sheet, [ctx.back, { text: "Preview again", kind: "primary", onclick: event => {
        if (preconAddHere(ctx, p, event.currentTarget) && colActive(cv) && !ctx.busy) previewPrecon(ctx, p.deck, ctx.titleInput.value.trim());
      } }]);
      return;
    }
    if (error.status === 409 && data.sha256) {
      // The collection changed since the preview: a precon only adds, so it can go on top of the latest.
      p.sha256 = cv.sha256 = data.sha256;
      if (Array.isArray(data.rows)) colTakeRows(cv, data);
      clear(ctx.message).append(el("div", { class: "box box-warn", role: "alert" }, el("p", { text: error.message }),
        el("p", { text: "Nothing was added yet. A precon only adds cards, so it can go on top of the latest list." })));
      sheetActions(ctx.sheet, [ctx.back, { text: "Add to the latest list", kind: "primary", value: "add", onclick: event => {
        if (preconAddHere(ctx, p, event.currentTarget)) addPrecon(ctx);
      } }]);
      return;
    }
    const problems = data.problems || (data.blocks || []).map((b) => ({ message: b.problem }));
    clear(ctx.message).append(el("div", { class: "box box-crit", role: "alert" }, el("p", { text: error.message }),
      problems.length ? el("ul", {}, problems.slice(0, 20).map((x) => el("li", { text: x.message }))) : null));
    // Nothing was saved: the cards and the deck go in together or not at all.
    if (error.status === 409 && data.conflict) {
      ctx.titleInput.focus();
    }
  }
}
