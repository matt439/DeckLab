/* Correct an order's record or a pending component. Every change has its
 * own preview; the server-issued token is the only input accepted by Save. */
"use strict";

function shopMayEditOrder(view) {
  return !!view && isAdminProfile() && mayDo("orders") && seesHomeInventory(state.may)
    && typeof view.data.queue_revision === "string" && !!view.data.queue_revision;
}

function shopOrderEditButton(order, view) {
  if (!shopMayEditOrder(view)) return null;
  return el("button", {type: "button", class: "btn btn-quiet shop-order-edit shop-queue-write",
    text: "Edit order…", "aria-label": `Edit ${shopOrderTitle(order)}`,
    onclick: () => shopOrderEditSheet(order, view)});
}

/** The record may be corrected after arrival; checks can change only while pending. */
function shopOrderEditSheet(order, view) {
  if (!shopMayEditOrder(view) || !shopQueueActive(view) || view.busy || view.stale) return null;
  const inputs = {}, form = el("form", {class: "shop-order-form"});
  const original = {seller: order.seller || "", ordered_on: order.ordered_on || "", notes: order.notes || "",
    sources: (order.sources || []).join("\n")};
  const changed = () => Object.fromEntries(Object.keys(original).filter(key => inputs[key].value !== original[key]).map(key =>
    [key, key === "sources" ? inputs.sources.value.split(/\r?\n/).filter(line => line.trim()) : inputs[key].value]));
  const edit = shopOrderChangeSheet(order, view, "Edit order", form, () => {
    const values = changed();
    if (!Object.keys(values).length) throw new Error("No order details have changed.");
    return {action: "record", values};
  });
  const changeCheck = (component, number = null) => {
    if (Object.keys(changed()).length) {
      edit.problem("Save or undo the order details before changing arrival checks.");
      return;
    }
    shopOrderCheckSheet(order, component, view, number);
  };
  const changeComponent = (component, extra = false, split = false) => {
    if (Object.keys(changed()).length) {
      edit.problem("Save or undo the order details before changing a component.");
      return;
    }
    if (split) shopOrderSplitSheet(order, component, view);
    else if (extra) shopOrderExtraSheet(order, component, view);
    else if (component.kind === "product") shopOrderProductSheet(order, component, view);
    else shopOrderRowsSheet(order, component, view);
  };
  const destructiveChange = (component = null) => {
    if (Object.keys(changed()).length) {
      edit.problem("Save or undo the order details before cancelling a part or removing the order.");
      return;
    }
    if (component) shopOrderCancelSheet(order, component, view);
    else shopOrderRemoveSheet(order, view);
  };
  const field = (where, key, label, tag, props) => {
    const input = el(tag, {id: `change-${key}-${edit.sheet.heading.id}`, "data-order-change-field": key, ...props});
    inputs[key] = input;
    where.append(el("label", {class: "field", for: input.id}, el("span", {text: label}), input));
    return input;
  };
  const grid = el("div", {class: "shop-order-grid"});
  field(grid, "seller", "Seller (if known)", "input", {type: "text", maxlength: 200, value: order.seller || ""});
  field(grid, "ordered_on", "Order date (if known)", "input", {type: "date", value: order.ordered_on || ""});
  form.append(el("p", {class: "sub", text: shopOrderTitle(order)}), grid);
  const notes = field(form, "notes", "Delivery notes", "input", {type: "text", maxlength: 2000});
  notes.value = order.notes || "";
  const sources = field(form, "sources", "Sources (one per line)", "textarea", {rows: 3, maxlength: 10000});
  sources.value = (order.sources || []).join("\n");
  form.append(el("p", {class: "field-hint", text: "Use repository-relative buylist or deck paths. Leave unknown details blank."}));
  for (const component of order.components || []) {
    if (component.status !== "pending") continue;
    const checks = component.checks || [];
    form.append(el("section", {class: "shop-order-section", "data-order-check-component": component.id},
      el("h3", {text: `${shopComponentWords(component)}: checks on arrival`}),
      checks.length ? el("ol", {}, checks.map((text, index) => el("li", {},
        el("span", {text}), " ", el("button", {type: "button", class: "btn btn-quiet",
          text: "Withdraw…", "aria-label": `Withdraw check ${index + 1}: ${text}`,
          onclick: () => changeCheck(component, index + 1)}))))
        : el("p", {class: "sub", text: "No arrival checks recorded."}),
      el("button", {type: "button", class: "btn btn-quiet", text: "Add check…",
        onclick: () => changeCheck(component)}),
      ["cards", "tokens"].includes(component.kind) && Array.isArray(component.edit_rows) && component.edit_rows.length
        ? el("button", {type: "button", class: "btn btn-quiet", text: component.kind === "cards" ? "Correct card details…" : "Correct token details…",
          onclick: () => changeComponent(component)}) : null,
      ["cards", "tokens"].includes(component.kind) && Array.isArray(component.edit_rows) && component.edit_rows.length
        ? el("button", {type: "button", class: "btn btn-quiet", text: "Split shipment…",
          "aria-label": `Split shipment ${component.id}`, onclick: () => changeComponent(component, false, true)}) : null,
      component.kind === "product" && component.edit_product
        ? el("button", {type: "button", class: "btn btn-quiet", text: "Correct product…",
          onclick: () => changeComponent(component)}) : null,
      ["cards", "product"].includes(component.kind) && typeof component.extra_copies === "boolean"
        ? el("button", {type: "button", class: "btn btn-quiet", text: component.extra_copies ? "Unmark additional copies…" : "Confirm additional copies…",
          onclick: () => changeComponent(component, true)}) : null,
      ["cards", "tokens", "product"].includes(component.kind) ? el("button", {type: "button", class: "btn btn-quiet",
        text: "Cancel part…", "aria-label": `Cancel part ${component.id}`, onclick: () => destructiveChange(component)}) : null));
  }
  const received = (order.components || []).some(component => component.status === "received");
  form.append(el("section", {class: "shop-order-section"}, el("h3", {text: "Recorded by mistake?"}),
    el("p", {class: "field-hint", text: received ? "An order cannot be removed once any part has been received."
      : "Remove an order recorded by mistake. Recorded fulfilled quantities return to To buy in the same change."}),
    el("button", {type: "button", class: "btn btn-danger btn-quiet", text: "Remove order…", disabled: received,
      "data-order-locked": received ? "true" : "false", onclick: () => destructiveChange()})));
  edit.bind();
  return edit.sheet;
}

function shopOrderCancelSheet(order, component, view) {
  if (!shopMayEditOrder(view) || !shopQueueActive(view) || view.busy || view.stale || component.status !== "pending"
      || !["cards", "tokens", "product"].includes(component.kind)) return null;
  return shopOrderEndSheet(order, view, component);
}

function shopOrderRemoveSheet(order, view) {
  if (!shopMayEditOrder(view) || !shopQueueActive(view) || view.busy || view.stale
      || (order.components || []).some(component => component.status === "received")) return null;
  return shopOrderEndSheet(order, view);
}

/** Cancellation keeps its record; removal is for an order entered by mistake. */
function shopOrderEndSheet(order, view, component = null) {
  const removing = !component, form = el("form", {class: "shop-order-form"});
  const reason = el("input", {type: "text", maxlength: 2000, required: true, "data-order-change-field": "reason"});
  const restore = removing ? null : el("input", {type: "checkbox", checked: true, "data-order-change-field": "restore_queue"});
  const edit = shopOrderChangeSheet(order, view, removing ? "Remove order" : "Cancel order part", form, () => {
    if (!reason.value.trim()) throw new Error(removing ? "Enter why this order should be removed." : "Enter why this part is being cancelled.");
    return removing ? {action: "remove", reason: reason.value.trim()}
      : {action: "cancel", component: component.id, reason: reason.value.trim(), restore_queue: restore.checked};
  }, {saveText: removing ? "Remove order" : "Cancel part", saveKind: "danger btn-primary",
    busyText: removing ? "Removing…" : "Cancelling…", retainResult: true});
  reason.id = `order-reason-${edit.sheet.heading.id}`;
  form.append(el("p", {text: shopOrderTitle(order)}),
    el("p", {text: removing ? "Remove this record, its parts and any never-received product. Its cards will stop counting as on the way."
      : `${shopComponentWords(component)} will be kept as cancelled and will stop counting as on the way.`}),
    el("label", {class: "field", for: reason.id}, el("span", {text: "Reason"}), reason));
  if (restore) form.append(el("label", {class: "choice"}, restore,
    el("span", {text: "Put this part's recorded fulfilled quantities back on To buy."})));
  else form.append(el("p", {text: "Its recorded fulfilled quantities will return to To buy in the same change."}));
  form.append(el("p", {class: "field-hint", text: "Preview shows the exact queue rows and deck tables affected. Older orders without fulfilment records need a manual queue review; no quantities are guessed."}));
  edit.bind();
  return edit.sheet;
}

/** A check is a separate operation, so it cannot also save unfinished record edits. */
function shopOrderCheckSheet(order, component, view, number = null) {
  if (!shopMayEditOrder(view) || !shopQueueActive(view) || view.busy || view.stale || component.status !== "pending") return null;
  const form = el("form", {class: "shop-order-form"});
  const input = number === null ? el("input", {type: "text", maxlength: 2000, "data-order-change-field": "check"}) : null;
  const rows = orderCheckTargeting(component, component.edit_rows) ? component.edit_rows.map(row => ({...row})) : null;
  const source = rows ? component.check_targeting.payload_sha256 : null, originalRows = rows ? JSON.stringify(rows) : null;
  const rowShas = rows ? [...component.check_targeting.row_sha256s] : null;
  const target = input && rows ? el("select", {"data-order-change-field": "check_target"},
    el("option", {value: "", text: "General check for this whole part"}), rows.map((row, index) =>
      el("option", {value: String(index + 1), text: orderCheckRowLabel(component.kind, row, index + 1)}))) : null;
  const edit = shopOrderChangeSheet(order, view, number === null ? "Add arrival check" : "Withdraw arrival check", form, () => {
    if (number !== null) return {action: "checks", component: component.id, withdraw: [number]};
    const text = input.value.trim();
    if (!text) throw new Error("Enter the check to add.");
    const body = {action: "checks", component: component.id, add: [text]};
    if (target?.value) {
      if (!/^[1-9]\d*$/.test(target.value) || !rows[Number(target.value) - 1]
          || !orderCheckTargeting(component, component.edit_rows) || component.check_targeting.payload_sha256 !== source
          || JSON.stringify(component.check_targeting.row_sha256s) !== JSON.stringify(rowShas)
          || JSON.stringify(component.edit_rows) !== originalRows) throw new Error("The original order rows changed. Refresh Shopping before choosing a row.");
      body.target = {row: Number(target.value), payload_sha256: source};
    }
    return body;
  }, {validatePreview: number === null ? shopCheckTargetReceipt : null,
    targetContext: rows ? {component: component.id, kind: component.kind, rows, rowShas, nextCheck: component.checks.length + 1} : null});
  form.append(el("p", {text: `${shopOrderTitle(order)} · ${shopComponentWords(component)}`}));
  if (input) {
    input.id = `arrival-check-${edit.sheet.heading.id}`;
    form.append(el("label", {class: "field", for: input.id}, el("span", {text: "Check on arrival"}), input));
    if (target) {
      target.id = `arrival-check-target-${edit.sheet.heading.id}`;
      form.append(el("label", {class: "field", for: target.id}, el("span", {text: "About an original order row (optional)"}), target),
        el("p", {class: "field-hint", text: "Leave this general unless you choose one exact recorded row. The check still needs verifying for the whole delivery part."}));
    }
  } else {
    form.append(el("p", {text: `Check ${number}: ${component.checks[number - 1]}`}),
      el("p", {class: "field-hint", text: "Withdraw a check added by mistake. The receipt verifies checks when the delivery arrives."}));
  }
  edit.bind();
  return edit.sheet;
}

/** Share request, stale-state and picker lifecycle across every order correction. */
function shopOrderChangeSheet(order, view, title, form, values, options = {}) {
  const expect = view.data.queue_revision;
  const sheet = shopTrackQueueSheet(openSheet({title, wide: true, onClose: () => {
    sequence++; preview = null; if (picker) picker.close();
    if (saved && !refreshed) {
      refreshed = true;
      setTimeout(() => {if (shopQueueActive(view)) {shopCloseQueueSheets(view); route();}}, 0);
    }
  }}), view);
  const previewBox = el("div", {class: "shop-order-preview", hidden: true, "aria-live": "polite"});
  const error = el("div", {class: "form-error", role: "alert", hidden: true});
  const acceptedControls = new WeakMap();
  let preview = null, previewBody = "", sequence = 0, busyNow = false, picking = false, picker = null, saved = false, refreshed = false;
  const alive = () => !sheet.closed && shopQueueActive(view) && shopMayEditOrder(view);
  const available = () => alive() && !saved && !busyNow && !picking && !view.busy && !view.stale;
  const payload = () => ({expect, order: order.id, ...values()});
  const problem = words => {error.textContent = words; error.hidden = false;};
  sheet.queueError = error;
  function actions() {
    if (saved) {sheetActions(sheet, [{text: "Done", kind: "primary", onclick: () => sheet.close()}]); shopSheetBusy(sheet, false); return;}
    sheetActions(sheet, [{text: "Cancel", disabled: busyNow || picking, onclick: () => sheet.close()},
      preview ? {text: "Back to edit", disabled: busyNow || view.busy, onclick: () => {invalidate(); error.hidden = true;}} : null,
      {text: preview ? options.saveText || "Save change" : "Preview change", kind: preview ? options.saveKind || "primary" : "primary", disabled: busyNow || picking || view.busy || view.stale,
        onclick: () => preview ? save() : review()}]);
    shopSheetBusy(sheet, busyNow, preview ? options.busyText || "Saving…" : "Previewing…");
  }
  function invalidate() {
    if (saved) return;
    sequence++; preview = null; previewBody = "";
    previewBox.hidden = true; form.hidden = false; actions();
  }
  sheet.queueBusy = () => {
    for (const tag of ["input", "textarea", "button", "select"])
      form.querySelectorAll(tag).forEach(control => {control.disabled = busyNow || picking || view.busy || view.stale || control.dataset.orderLocked === "true";});
    actions();
  };
  function setBusy(value) {busyNow = value; shopQueueBusy(view, value);}
  function conflictRefresh() {
    if (view.stale) error.append(el("button", {type: "button", class: "btn btn-quiet", text: "Refresh Shopping",
      onclick: () => {shopCloseQueueSheets(view); route();}}));
  }
  async function review() {
    if (!available()) return;
    let body;
    try {body = payload();} catch (failure) {problem(failure.message); return;}
    const original = JSON.stringify(body), seq = ++sequence;
    preview = null; previewBody = ""; error.hidden = true; setBusy(true);
    try {
      const answer = await apiWrite("/api/shopping/order/change/preview", body);
      if (!alive() || seq !== sequence || original !== JSON.stringify(payload())) return;
      if (!answer.preview || answer.revision !== expect) throw new Error("The preview was incomplete. Preview the change again.");
      if (options.validatePreview) options.validatePreview(answer, body, options.targetContext);
      preview = answer.preview; previewBody = original;
      clear(previewBox).append(shopOrderChangePreview(answer, body, false, options.targetContext));
      previewBox.hidden = false; form.hidden = true; previewBox.scrollIntoView({block: "start"});
    } catch (failure) {
      if (alive()) {
        if (failure.status === 409) view.stale = true;
        problem(`The change couldn't be previewed: ${failure.message}`); conflictRefresh();
      }
    } finally {if (alive()) setBusy(false); else shopQueueBusy(view, false);}
  }
  async function save() {
    if (!available() || !preview) return;
    try {
      if (previewBody !== JSON.stringify(payload())) {invalidate(); problem("The change was edited. Preview it again before saving."); return;}
    } catch (failure) {invalidate(); problem(failure.message); return;}
    const token = preview, signedBody = JSON.parse(previewBody), targeted = Boolean(options.validatePreview && signedBody.target);
    let uncertainTarget = false;
    error.hidden = true; setBusy(true);
    try {
      const answer = await apiWrite("/api/shopping/order/change/apply", {preview: token});
      if (targeted) {
        try {
          if (answer.saved !== true) throw new Error("No saved receipt");
          options.validatePreview(answer, signedBody, options.targetContext);
        } catch (failure) { uncertainTarget = true; throw failure; }
      }
      state.library = null;
      if (!alive()) {
        if (shopQueueActive(view)) {shopCloseQueueSheets(view); route();}
        return;
      }
      preview = null;
      if (options.retainResult) {
        saved = true; error.hidden = true; form.hidden = true; previewBox.hidden = false;
        clear(previewBox).append(shopOrderChangePreview(answer, JSON.parse(previewBody), true, options.targetContext));
        actions(); return;
      }
      shopCloseQueueSheets(view);
      toast(answer.tables && answer.tables.error ? `Order updated. Deck tables need attention: ${answer.tables.error}` : "Order updated.");
      route();
    } catch (failure) {
      if (alive()) {
        uncertainTarget ||= targeted && (!failure.status || failure.status >= 500);
        invalidate(); if (failure.status === 409 || uncertainTarget) view.stale = true;
        problem(uncertainTarget ? "The saved row association couldn't be confirmed. Refresh Shopping and inspect the saved checks before making another change."
          : `The change couldn't be saved: ${failure.message}. Preview it again before saving.`); conflictRefresh();
      }
    } finally {if (alive()) setBusy(false); else shopQueueBusy(view, false);}
  }
  sheet.body.append(form, previewBox, error);
  form.addEventListener("submit", event => {event.preventDefault(); review();});
  return {sheet, problem, alive, available, invalidate, async printing(name, current) {
    if (!available()) return null;
    invalidate(); picking = true; sheet.queueBusy();
    try {
      const picked = await pickPrinting(name, {current, title: `Ordered printing of ${name}`, onOpen: opened => {
        picker = shopTrackQueueSheet(opened, view);
        if (!alive()) picker.close();
      }});
      return alive() && !view.stale ? picked : null;
    } catch (failure) {
      if (alive()) problem(`The printing picker couldn't open: ${failure.message}`);
      return null;
    } finally {picker = null; picking = false; if (alive()) sheet.queueBusy();}
  }, bind() {
    for (const tag of ["input", "textarea", "select"]) for (const input of form.querySelectorAll(tag)) {
      if (acceptedControls.has(input)) continue;
      const value = () => ["checkbox", "radio"].includes(input.getAttribute("type")) ? Boolean(input.checked) : input.value;
      acceptedControls.set(input, value());
      const changed = () => {
        const next = value();
        if (next === acceptedControls.get(input)) return;
        acceptedControls.set(input, next); invalidate();
      };
      input.addEventListener("input", changed); input.addEventListener("change", changed);
    }
    actions(); sheet.heading.focus();
  }};
}

function shopOrderChangePreview(answer, body = null, saved = false, targetContext = null) {
  const record = answer.record || {}, box = el("div", {}, el("h3", {text: saved
    ? answer.removed ? "Order removed" : "Order change saved" : "Confirm this change"}),
    el("p", {text: answer.summary}), el("p", {text: answer.order}));
  if (body?.reason) box.append(el("p", {text: `Reason: ${body.reason}`}));
  const checkTarget = shopCheckTargetPreview(answer, targetContext);
  if (checkTarget) box.append(checkTarget);
  box.append(el("dl", {}, el("dt", {text: "Seller"}), el("dd", {text: record.seller || "Not recorded"}),
    el("dt", {text: "Order date"}), el("dd", {text: record.ordered_on ? shopDay(record.ordered_on) : "Not recorded"}),
    el("dt", {text: "Delivery notes"}), el("dd", {text: record.notes || "None recorded"})));
  const sources = record.sources || [];
  box.append(el("h4", {text: "Sources"}), sources.length ? el("ul", {}, sources.map(text => el("li", {text})))
    : el("p", {text: "None recorded."}));
  if ((answer.changes || []).length) box.append(el("ul", {}, answer.changes.map(text => el("li", {text}))));
  if (answer.component) box.append(answer.action === "cancel" || body?.action === "cancel"
    ? el("p", {text: `Part ${answer.component.id}: cancelled`}) : shopOrderComponentPreview(answer.component));
  if (Array.isArray(answer.components)) box.append(shopOrderSplitPreview(answer));
  const queue = answer.queue_restoration;
  if (queue) {
    const restored = queue.restored || [], offered = queue.offered || [];
    box.append(el("h4", {text: saved ? "Returned to To buy" : "Queue quantities to return"}));
    if (restored.length) box.append(el("ul", {}, restored.map(row => el("li", {text:
      `${row.quantity} x ${row.name}${row.for ? ` for ${row.for}` : ""} · ${shopPrinting(row)}${row.state ? ` · ${SHOPPING_STATES[row.state] || row.state}` : ""}`}))));
    else box.append(el("p", {text: offered.length ? "No queue quantities will be returned with this choice." : "No recorded queue quantities are available to return."}));
    if (offered.length && !restored.length) box.append(el("h4", {text: "Recorded fulfilled quantities left off the queue"}),
      el("ul", {}, offered.map(row => el("li", {text: `${row.quantity} x ${row.name}${row.for ? ` for ${row.for}` : ""} · ${shopPrinting(row)}`}))));
    if (queue.known === false) box.append(el("p", {class: "note note-warn", text: "This order has no complete fulfilment record. Review To buy manually; no quantities are guessed."}));
    if ((queue.warnings || []).length) add(box, [warningsBox(queue.warnings, saved ? "Queue needs review" : "Check the queue restoration")]);
  }
  for (const part of answer.checks || []) {
    if ((answer.components || []).some(component => component.id === part.component)) continue;
    box.append(el("h4", {text: `Checks on arrival: ${part.component}`}),
    part.checks.length ? el("ol", {}, part.checks.map(text => el("li", {text}))) : el("p", {text: "No checks recorded."}));
  }
  const tables = answer.tables || {};
  if ((tables.written || []).length) box.append(el("h4", {text: "Deck tables"}), el("ul", {}, tables.written.map(deck =>
    el("li", {}, el("a", {href: deckHref(deck.id), text: deck.title || deck.id})))));
  if ((tables.skipped || []).length) box.append(el("p", {class: "note note-warn", text: `Not updated: ${tables.skipped.map(deck => deck.title || deck.id).join(", ")}.`}));
  if (tables.error) box.append(el("p", {class: "note note-warn", text: tables.error}));
  if ((tables.skipped || []).length || tables.error) box.append(el("a", {href: TABLES_HREF, text: "Tables out of date"}));
  if ((answer.warnings || []).length) add(box, [warningsBox(answer.warnings, saved ? "Saved, with notes" : "Check before saving")]);
  return box;
}
