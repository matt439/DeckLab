/* Record a placed order on Shopping. Preview and confirmation use the same guarded
 * inventory operation as the command line; only its server-issued preview can save. */
"use strict";

const SHOP_ORDER_FIELDS = ["name", "set", "collector_number", "finish", "quantity", "condition", "language", "notes"];

/** Read quoted CSV, including commas, newlines and escaped quotes inside a field. */
function shopOrderCSV(text) {
  const rows = [], row = []; let value = "", quoted = false;
  text = String(text).replace(/^\uFEFF/, "").replace(/\r\n?/g, "\n");
  for (let at = 0; at <= text.length; at++) {
    const char = text[at];
    if (char === '"') {
      if (quoted && text[at + 1] === '"') { value += '"'; at++; }
      else if (quoted || !value) quoted = !quoted;
      else throw new Error("A quote must start a CSV field.");
    } else if (!quoted && (char === "," || char === "\n" || char === undefined)) {
      row.push(value); value = "";
      if (char !== ",") { if (row.some(part => part.trim())) rows.push([...row]); row.length = 0; }
    } else if (char !== undefined) value += char;
  }
  if (quoted) throw new Error("A quoted CSV field isn't closed.");
  if (rows.length < 2) throw new Error("Paste a header and at least one card row.");
  const columns = rows.shift().map(part => part.trim().toLowerCase());
  if (new Set(columns).size !== columns.length) throw new Error("The CSV has a repeated column.");
  return rows.map((parts, index) => {
    if (parts.length !== columns.length) throw new Error(`CSV row ${index + 2} has ${parts.length} fields; expected ${columns.length}.`);
    return Object.fromEntries(columns.map((key, n) => [key, parts[n].trim()]));
  });
}

/** Plain lists may omit printing: its row then asks for one before previewing. */
function shopOrderCards(text) {
  if (/(?:^|,)\s*"?name"?\s*(?:,|$)/i.test(text.split(/\r?\n/)[0])) {
    return shopOrderCSV(text).map(row => {
      if (!row.name) throw new Error("Every card row needs a name.");
      return Object.fromEntries(SHOP_ORDER_FIELDS.map(key => [key, row[key] || (key === "finish" ? "nonfoil" : "")]));
    });
  }
  return text.split(/\r?\n/).map(line => line.trim()).filter(Boolean).map((line, index) => {
    const match = /^(\d+)\s*x?\s+(.+?)(?:\s+\(([a-zA-Z0-9]+)\)\s+([a-zA-Z0-9-]+)(?:\s+(nonfoil|foil|etched))?)?$/.exec(line);
    if (!match) throw new Error(`Line ${index + 1}: use a quantity then a card name, such as 2 Llanowar Elves.`);
    return {name: match[2], set: (match[3] || "").toLowerCase(), collector_number: match[4] || "",
      finish: match[5] || "nonfoil", quantity: match[1], condition: "", language: "", notes: ""};
  });
}

function shopOrderToday() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

/** The existing sheet lifecycle closes this form and its pickers on profile or route changes. */
function shopOrderSheet(view) {
  if (!isAdminProfile() || !mayDo("orders") || !seesHomeInventory(state.may)
      || !shopQueueActive(view) || view.busy || view.stale || !view.data.queue_revision) return null;
  const sheet = shopTrackQueueSheet(openSheet({title: "Record an order", wide: true}), view);
  const form = el("form", {class: "shop-order-form"}), inputs = {}, cards = [], selections = [];
  const cardList = el("div", {class: "shop-order-cards"});
  const error = el("div", {class: "form-error", role: "alert", hidden: true});
  const previewBox = el("div", {class: "shop-order-preview", hidden: true, "aria-live": "polite"});
  let preview = null, previewBody = "", sequence = 0, busyNow = false, nameTimer = null, nameSequence = 0, referenceTyped = false;
  const alive = () => !sheet.closed && shopQueueActive(view);
  sheet.orderError = error;
  const field = (where, key, label, tag = "input", props = {}, children = []) => {
    const input = el(tag, {id: `order-${key}-${sheet.heading.id}`, "data-order-field": key, ...props}, children);
    inputs[key] = input;
    where.append(el("label", {class: "field", for: input.id}, el("span", {text: label}), input));
    input.addEventListener("input", invalidate);
    input.addEventListener("change", invalidate);
    return input;
  };
  const problem = (words, focus = null) => { error.textContent = words; error.hidden = false; if (focus) focus.focus(); };
  function invalidate() {
    sequence++; preview = null; previewBody = "";
    if (!previewBox.hidden) { previewBox.hidden = true; form.hidden = false; actions(); }
  }
  function actions() {
    sheetActions(sheet, [{text: "Cancel", disabled: busyNow, onclick: () => sheet.close()},
      preview ? {text: "Edit order", disabled: busyNow, onclick: () => { invalidate(); error.hidden = true; }} : null,
      {text: preview ? "Save order" : "Preview order", kind: "primary", disabled: busyNow || view.stale,
        onclick: () => preview ? save() : review()}]);
  }
  const metadata = el("div", {class: "shop-order-grid"});
  field(metadata, "seller", "Seller (if known)", "input", {type: "text", maxlength: 200});
  field(metadata, "ordered_on", "Order date (if known)", "input", {type: "date"});
  const reference = field(metadata, "id", "Order reference", "input", {type: "text", required: true, maxlength: 100,
    value: `${shopOrderToday()}-order`, autocapitalize: "none", spellcheck: "false"});
  reference.addEventListener("input", () => {referenceTyped = true;});
  const suggestReference = () => {
    if (!referenceTyped) reference.value = `${inputs.ordered_on.value || shopOrderToday()}-${inputs.seller.value.toLowerCase()
      .replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "order"}`;
  };
  inputs.seller.addEventListener("input", suggestReference);
  inputs.ordered_on.addEventListener("input", suggestReference);
  form.append(metadata, el("p", {class: "field-hint", text: "The reference identifies this delivery. Use a date and short label; change it for separate shipments."}));
  field(form, "notes", "Delivery notes (optional)", "input", {type: "text", maxlength: 2000});

  const singles = el("section", {class: "shop-order-section"}, el("h3", {text: "Cards"}));
  const finder = el("div", {class: "shop-order-search"});
  const names = el("datalist", {id: `order-names-${sheet.heading.id}`});
  const name = field(finder, "card_name", "Find a card", "input", {type: "text", maxlength: 150, autocomplete: "off",
    autocapitalize: "none", spellcheck: "false", list: names.id});
  const qty = field(finder, "card_quantity", "Copies", "input", {type: "number", inputmode: "numeric", min: 1,
    max: 9999, step: 1, value: 1});
  name.addEventListener("input", () => {
    clearTimeout(nameTimer); const seq = ++nameSequence, query = name.value.trim(); clear(names);
    if (query.length < 2) return;
    nameTimer = setTimeout(async () => {
      try {
        const result = await api(`/api/cards/search?q=${encodeURIComponent(query)}&limit=8`);
        if (alive() && seq === nameSequence && query === name.value.trim())
          add(names, (result.cards || []).map(card => el("option", {value: card.name})));
      } catch (failure) { if (alive() && seq === nameSequence) problem(`Card search couldn't load: ${failure.message}. You can still enter its full name.`); }
    }, 180);
  });
  finder.append(el("button", {type: "button", class: "btn", text: "Choose printing and add…", onclick: async () => {
    if (!alive() || busyNow) return;
    const wanted = name.value.trim(), quantity = Number(qty.value);
    if (!wanted) return problem("Enter a card name.", name);
    if (!Number.isInteger(quantity) || quantity < 1 || quantity > 9999) return problem("Copies must be a whole number from 1 to 9999.", qty);
    const picked = await pickPrinting(wanted, {title: `Ordered printing of ${wanted}`, onOpen: picker => shopTrackQueueSheet(picker, view)});
    if (!alive() || name.value.trim() !== wanted || !picked) return;
    if (!picked.set) return problem("Choose the printing that was ordered, including for basic lands.");
    cards.push({name: wanted, set: picked.set, collector_number: picked.number, finish: picked.finish,
      quantity, condition: "", language: "", notes: ""});
    invalidate(); drawCards(); name.value = ""; qty.value = "1"; error.hidden = true;
  }}));
  const paste = el("details", {class: "shop-order-paste"}, el("summary", {text: "Paste a card list"}));
  const text = field(paste, "cards_text", "Cards to add", "textarea", {rows: 4, maxlength: 250000,
    placeholder: "2 Llanowar Elves\n1 Sol Ring (CMM) 396 nonfoil"});
  paste.append(el("p", {class: "field-hint", text: "Use quantity and name on each line, optionally (SET) collector-number finish. Or paste CSV headed name,set,collector_number,finish,quantity,condition,language,notes. Unknown condition and language stay blank."}),
    el("button", {type: "button", class: "btn", text: "Add pasted cards", onclick: () => {
      if (!alive() || busyNow) return;
      try {
        const added = shopOrderCards(text.value);
        if (!added.length) throw new Error("Paste at least one card.");
        cards.push(...added); text.value = ""; invalidate(); drawCards(); error.hidden = true;
      } catch (failure) { problem(failure.message, text); }
    }}));
  singles.append(finder, names, paste, cardList);
  field(singles, "cards_checks", "Check these cards on arrival (one per line)", "textarea", {rows: 2, maxlength: 4000});
  const extraCards = field(singles, "cards_extra", "These are additional copies of printings already owned", "input", {type: "checkbox"});
  singles.append(el("p", {class: "field-hint", text: "Only tick this when these are more physical copies, rather than cards already added to the collection."}));
  form.append(singles);

  function drawCards() {
    clear(cardList);
    cards.forEach((card, index) => {
      const quantity = el("input", {type: "number", inputmode: "numeric", min: 1, max: 9999, value: card.quantity,
        "aria-label": `Copies of ${card.name}`, "data-order-card-quantity": index, oninput: () => {card.quantity = quantity.value; invalidate();}});
      cardList.append(el("div", {class: "shop-order-card"}, el("div", {}, el("strong", {text: card.name}),
        el("small", {text: card.set ? `${card.set.toUpperCase()} ${card.collector_number} · ${card.finish}` : "Choose the ordered printing"}),
        card.notes ? el("small", {text: card.notes}) : null), quantity,
        el("button", {type: "button", class: "btn btn-quiet", text: "Printing…", "aria-label": `Printing of ${card.name}`, onclick: async () => {
          if (!alive() || busyNow) return;
          const picked = await pickPrinting(card.name, {current: {set: card.set, number: card.collector_number, finish: card.finish},
            onOpen: picker => shopTrackQueueSheet(picker, view)});
          if (alive() && cards.includes(card) && picked && picked.set) {
            Object.assign(card, {set: picked.set, collector_number: picked.number, finish: picked.finish}); invalidate(); drawCards();
          }
        }}), el("button", {type: "button", class: "btn btn-quiet", text: "Remove", "aria-label": `Remove ${card.name} from this order`,
          onclick: () => {if (!busyNow) {cards.splice(cards.indexOf(card), 1); invalidate(); drawCards();}}})));
    });
  }

  const tokens = el("details", {class: "shop-order-section"}, el("summary", {text: "Token or reminder singles"}));
  field(tokens, "tokens_csv", "Token card list (CSV)", "textarea", {rows: 4, maxlength: 250000,
    placeholder: "front,back,set,front_collector_number,back_collector_number,finish,quantity,front_details,back_details,notes"});
  tokens.append(el("p", {class: "field-hint", text: "Each row is one physical card: keep its front/back pairing and count physical copies. Leave unknown printings and characteristics blank. Tokens are inspected when the delivery arrives."}));
  field(tokens, "tokens_checks", "Check these tokens on arrival (one per line)", "textarea", {rows: 2, maxlength: 4000});
  form.append(tokens);

  const product = el("details", {class: "shop-order-section"}, el("summary", {text: "A sealed product"}));
  const productGrid = el("div", {class: "shop-order-grid"});
  field(productGrid, "product_stem", "Product reference", "input", {type: "text", maxlength: 100, placeholder: "fdc-goblin-horde"});
  field(productGrid, "product_name", "Product name", "input", {type: "text", maxlength: 200});
  field(productGrid, "product_format", "Format (optional)", "input", {type: "text", maxlength: 200, placeholder: "Commander precon (100 cards)"});
  const productStatus = field(productGrid, "product_status", "Status", "select", {},
    [el("option", {value: "ordered", text: "Ordered"}), el("option", {value: "preordered", text: "Preordered"})]);
  productStatus.value = "ordered"; product.append(productGrid);
  field(product, "product_csv", "Product's card list (CSV)", "textarea", {rows: 4, maxlength: 1000000,
    placeholder: "name,set,collector_number,finish,quantity,section,deck"});
  product.append(el("p", {class: "field-hint", text: "Include every playable card and basic land. The optional section and deck columns identify its decks. Product token cards are recorded after inspection on arrival."}));
  field(product, "product_checks", "Check this product on arrival (one per line)", "textarea", {rows: 2, maxlength: 4000});
  const extraProduct = field(product, "product_extra", "This product contains additional copies of printings already owned", "input", {type: "checkbox"});
  form.append(product);

  if ((view.data.to_buy || []).length) {
    const queue = el("section", {class: "shop-order-section"}, el("h3", {text: "Purchase queue"}),
      el("p", {class: "field-hint", text: "Tick only rows this order covers, then enter the copies to take off the queue. Other copies stay queued."}));
    for (const card of view.data.to_buy) {
      const checked = el("input", {type: "checkbox", "data-order-fulfils": card.queue_row, onchange: invalidate});
      const quantity = el("input", {type: "number", min: 1, max: card.quantity, value: card.quantity,
        "aria-label": `Queued copies of ${card.name} fulfilled`, "data-order-fulfils-quantity": card.queue_row, oninput: invalidate});
      selections.push({card, checked, quantity});
      queue.append(el("div", {class: "shop-order-queue"}, el("label", {}, checked,
        el("span", {}, el("strong", {text: card.name}), el("small", {text: [card.for, shopPrinting(card), `${card.quantity} queued`].filter(Boolean).join(" · ")}))), quantity));
    }
    form.append(queue);
  }
  sheet.body.append(form, previewBox, error);
  form.addEventListener("submit", event => {event.preventDefault(); review();});
  sheet.dialog.addEventListener("close", () => {clearTimeout(nameTimer); sequence++;});

  function payload() {
    if (text.value.trim()) throw new Error("Add the pasted cards before previewing the order.");
    if (name.value.trim()) throw new Error("Choose a printing and add the card before previewing the order.");
    if (!inputs.id.value.trim()) throw new Error("Enter an order reference.");
    for (const card of cards) {
      if (!card.set || !card.collector_number) throw new Error(`Choose the ordered printing of ${card.name}.`);
      if (!Number.isInteger(Number(card.quantity)) || Number(card.quantity) < 1 || Number(card.quantity) > 9999)
        throw new Error(`Copies of ${card.name} must be a whole number from 1 to 9999.`);
    }
    const lines = key => inputs[key].value.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
    const body = {expect: view.data.queue_revision, record: {id: inputs.id.value.trim(), seller: inputs.seller.value.trim(),
      ordered_on: inputs.ordered_on.value, notes: inputs.notes.value.trim()}, fulfils: [], extra_copies: []};
    if (cards.length) body.cards = {rows: cards.map(card => ({...card, quantity: Number(card.quantity)})), checks: lines("cards_checks")};
    if (inputs.tokens_csv.value.trim()) body.tokens = {csv: inputs.tokens_csv.value, checks: lines("tokens_checks")};
    if (inputs.product_stem.value.trim() || inputs.product_csv.value.trim() || inputs.product_name.value.trim()) {
      body.product = {stem: inputs.product_stem.value.trim(), status: productStatus.value,
        csv: inputs.product_csv.value, checks: lines("product_checks")};
      if (inputs.product_name.value.trim()) body.product.name = inputs.product_name.value.trim();
      if (inputs.product_format.value.trim()) body.product.format = inputs.product_format.value.trim();
    }
    if (!body.cards && !body.tokens && !body.product) throw new Error("Add cards, token singles or a product to this order.");
    if (extraCards.checked && body.cards) body.extra_copies.push("cards");
    if (extraProduct.checked && body.product) body.extra_copies.push(body.product.stem);
    for (const {card, checked, quantity} of selections) if (checked.checked) {
      const copies = Number(quantity.value);
      if (!Number.isInteger(copies) || copies < 1 || copies > card.quantity)
        throw new Error(`Fulfilled copies of ${card.name} must be a whole number from 1 to ${card.quantity}.`);
      body.fulfils.push({row: card.queue_row, quantity: copies});
    }
    return body;
  }
  function setBusy(value) {
    busyNow = value; shopQueueBusy(view, value);
    form.querySelectorAll("input").forEach(input => {input.disabled = value;});
    form.querySelectorAll("textarea").forEach(input => {input.disabled = value;});
    form.querySelectorAll("select").forEach(input => {input.disabled = value;});
    form.querySelectorAll("button").forEach(input => {input.disabled = value;});
    actions();
  }
  async function review() {
    if (!alive() || busyNow || view.busy || view.stale || !isAdminProfile()) return;
    let body;
    try {body = payload();} catch (failure) {problem(failure.message); return;}
    const seq = ++sequence, original = JSON.stringify(body); error.hidden = true; setBusy(true);
    try {
      const answer = await apiWrite("/api/shopping/order/preview", body);
      if (!alive() || seq !== sequence || original !== JSON.stringify(payload())) return;
      preview = answer.preview; previewBody = original;
      clear(previewBox).append(shopOrderPreview(answer, body)); previewBox.hidden = false; form.hidden = true;
      previewBox.scrollIntoView({block: "start"});
    } catch (failure) {
      if (alive()) {
        if (failure.status === 409) view.stale = true;
        problem(`The order couldn't be previewed: ${failure.message}`); conflictRefresh();
      }
    } finally {if (alive()) setBusy(false); else shopQueueBusy(view, false);}
  }
  function conflictRefresh() {
    if (view.stale) error.append(el("button", {type: "button", class: "btn btn-quiet", text: "Refresh Shopping",
      onclick: () => {shopCloseQueueSheets(view); route();}}));
  }
  async function save() {
    if (!alive() || busyNow || view.busy || view.stale || !preview || !isAdminProfile()) return;
    try {
      if (previewBody !== JSON.stringify(payload())) {invalidate(); problem("The order changed. Preview it again before saving."); return;}
    } catch (failure) {invalidate(); problem(failure.message); return;}
    const token = preview; error.hidden = true; setBusy(true);
    try {
      const answer = await apiWrite("/api/shopping/order/apply", {preview: token});
      if (!alive()) return;
      preview = null; sheet.close();
      toast(answer.tables && answer.tables.error ? `Order recorded. Deck tables need attention: ${answer.tables.error}` : "Order recorded under On the way.");
      route();
    } catch (failure) {
      if (alive()) {
        invalidate(); if (failure.status === 409) view.stale = true;
        problem(`The order couldn't be saved: ${failure.message}. Preview it again before saving.`); conflictRefresh();
      }
    } finally {if (alive()) setBusy(false); else shopQueueBusy(view, false);}
  }
  actions(); sheet.heading.focus();
  return sheet;
}

/** All effects are reviewable before Save: delivery checks, queue reductions and deck refreshes. */
function shopOrderPreview(answer, body) {
  const box = el("div", {}, el("h3", {text: "Confirm this order"}), el("p", {text: answer.summary || "Record this order as on the way."}));
  box.append(el("p", {text: [body.record.id, body.record.seller,
    body.record.ordered_on ? `Ordered ${shopDay(body.record.ordered_on)}` : "Order date not recorded"].filter(Boolean).join(" · ")}));
  if (body.record.notes) box.append(el("p", {text: body.record.notes}));
  if (body.cards) box.append(el("h4", {text: "Ordered cards"}), el("ul", {}, body.cards.rows.map(card =>
    el("li", {text: `${card.quantity} × ${card.name} · ${card.set.toUpperCase()} ${card.collector_number} · ${card.finish}${card.condition ? ` · ${card.condition}` : ""}${card.language ? ` · ${card.language}` : ""}${card.notes ? ` · ${card.notes}` : ""}`}))));
  if (body.tokens) box.append(el("h4", {text: "Token singles"}), el("pre", {class: "shop-order-csv", text: body.tokens.csv}));
  if (body.product) add(box, [el("h4", {text: `${body.product.name || body.product.stem} · ${body.product.status}`}),
    body.product.format ? el("p", {text: body.product.format}) : null,
    el("pre", {class: "shop-order-csv", text: body.product.csv})]);
  if (body.extra_copies.length) box.append(el("p", {text: `Confirmed additional copies of owned printings: ${body.extra_copies.join(", ")}.`}));
  if (answer.changes && answer.changes.length) box.append(el("ul", {}, answer.changes.map(change => el("li", {text: change}))));
  const checks = (answer.checks || []).flatMap(part => (part.checks || []).map(check => `${part.component}: ${check}`));
  if (checks.length) box.append(el("h4", {text: "Checks on arrival"}), el("ul", {}, checks.map(check => el("li", {text: check}))));
  if (answer.watchlist_reduced && answer.watchlist_reduced.length) box.append(el("h4", {text: "Purchase queue reductions"}),
    el("ul", {}, answer.watchlist_reduced.map(row => el("li", {text: `${row.name}${row.for ? ` · ${row.for}` : ""}: ${row.quantity} ordered, ${row.left} left queued`}))));
  const tables = answer.tables || {}, written = tables.written || [], skipped = tables.skipped || [];
  box.append(el("h4", {text: "Deck tables"}), written.length ? el("ul", {}, written.map(deck => el("li", {},
    el("a", {href: deckHref(deck.id), text: deck.title || deck.id})))) : el("p", {text: "No deck's table needs updating."}));
  if (skipped.length) box.append(el("p", {class: "note note-warn", text: `Not updated: ${skipped.map(deck => `${deck.title || deck.id}${deck.why ? ` (${deck.why})` : ""}`).join(", ")}.`}));
  if (tables.error) box.append(el("p", {class: "note note-warn", text: tables.error}));
  if (answer.warnings && answer.warnings.length) box.append(el("ul", {class: "note note-warn"}, answer.warnings.map(warning => el("li", {text: warning}))));
  box.append(el("p", {class: "field-hint", text: "Saving records the order and its queue reductions together. Its cards stay on the way until you receive the delivery."}));
  return box;
}
