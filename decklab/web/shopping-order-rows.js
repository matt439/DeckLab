/* Pending row corrections retain the exact recorded fields. These are corrections
 * to an order, so playable names and total physical quantities stay fixed. */
"use strict";

function shopOrderRowsSheet(order, component, view) {
  if (!shopMayEditOrder(view) || !shopQueueActive(view) || view.busy || view.stale || component.status !== "pending"
      || !["cards", "tokens"].includes(component.kind) || !Array.isArray(component.edit_rows) || !component.edit_rows.length) return null;
  const rows = component.edit_rows.map(row => ({...row})), controls = [];
  const form = el("form", {class: "shop-order-form"});
  const values = () => rows.map((row, index) => ({...row,
    ...Object.fromEntries(controls[index].map(([key, input, original, displayed]) =>
      [key, key === "quantity" ? Number(input.value) : input.value === displayed ? original : input.value]))}));
  const expectedTotal = component.edit_rows.reduce((sum, row) => sum + Number(row.quantity), 0);
  const counts = source => source.reduce((result, row) => {
    result[row.name] = (result[row.name] || 0) + Number(row.quantity); return result;
  }, {});
  const expectedNames = counts(component.edit_rows);
  const sync = () => values().forEach((row, index) => Object.assign(rows[index], row));
  const edit = shopOrderChangeSheet(order, view, component.kind === "cards" ? "Correct card details" : "Correct token details", form, () => {
    const corrected = values();
    if (corrected.some(row => !Number.isInteger(row.quantity) || row.quantity < 1 || row.quantity > 9999))
      throw new Error("Each row needs a whole number of physical copies from 1 to 9999.");
    if (corrected.reduce((sum, row) => sum + row.quantity, 0) !== expectedTotal)
      throw new Error(`Keep the same total: ${expectedTotal} physical copies. Adjust the row quantities before previewing.`);
    const names = counts(corrected);
    if (component.kind === "cards" && Object.keys(expectedNames).some(name => expectedNames[name] !== names[name]))
      throw new Error("Keep the same total quantity of each card name. Only its printing or recorded details can change.");
    if (JSON.stringify(corrected) === JSON.stringify(component.edit_rows.map(row => ({...row, quantity: Number(row.quantity)}))))
      throw new Error("No card details have changed.");
    return {action: "edit", component: component.id, rows: corrected};
  });
  form.append(el("p", {text: `${shopOrderTitle(order)} · ${shopComponentWords(component)}`}),
    el("p", {class: "field-hint", text: component.kind === "cards"
      ? "Correct the ordered printing, finish or recorded details. Keep the same total quantity of each card name; use Another printing to split copies between printings. Leave unknown condition and language blank."
      : "Correct the physical token cards, keeping each front/back pairing together. Keep the same total number of physical cards; use Another row to split pairings. Leave unknown printings and characteristics blank."}),
    el("p", {class: "sub", text: `Order total: ${expectedTotal} physical copies. This correction does not add or remove ordered cards.`}));
  const list = el("div", {class: "shop-order-form"}); form.append(list);
  function draw() {
    clear(list); controls.length = 0;
    rows.forEach((row, index) => {
    const removable = rows.length > 1 && (component.kind === "tokens" || rows.filter(other => other.name === row.name).length > 1);
    const fields = [], section = el("section", {class: "shop-order-section", "data-order-correction-row": index});
    controls.push(fields);
    section.append(el("h3", {text: `${index + 1}. ${row.quantity} × ${row.name || [row.front, row.back].filter(Boolean).join(" // ")}`}));
    const grid = el("div", {class: "shop-order-grid"});
    const field = (key, label, where = grid, multiline = false) => {
      const input = el(multiline ? "textarea" : "input", {id: `correct-${edit.sheet.heading.id}-${index}-${key}`,
        "data-order-row-field": key, "data-order-row": index, ...(multiline ? {rows: 2} : {type: "text"})});
      input.value = row[key] ?? "";
      // Native textareas display CRLF as LF. An untouched field still carries
      // its exact stored value when another field or printing is corrected.
      fields.push([key, input, row[key] ?? "", input.value]);
      input.addEventListener("input", edit.invalidate); input.addEventListener("change", edit.invalidate);
      where.append(el("label", {class: "field", for: input.id}, el("span", {text: label}), input));
      return input;
    };
    const quantity = field("quantity", "Physical copies");
    quantity.type = "number"; quantity.min = "1"; quantity.max = "9999"; quantity.inputMode = "numeric";
    if (component.kind === "cards") {
      const printing = el("p", {class: "sub"}), drawPrinting = () => {
        printing.textContent = `${row.set || "Set not recorded"} ${row.collector_number || ""} · ${row.finish || "Finish not recorded"}`;
      };
      drawPrinting();
      section.append(printing, el("button", {type: "button", class: "btn", text: "Printing…", "aria-label": `Correct printing of ${row.name}`,
        onclick: async () => {
          if (!edit.available()) return;
          const picked = await edit.printing(row.name, {set: row.set, number: row.collector_number, finish: row.finish});
          if (!picked || !edit.alive()) return;
          if (!picked.set) {edit.problem("Choose the ordered printing, including for basic lands."); return;}
          Object.assign(row, {set: picked.set, collector_number: picked.number, finish: picked.finish});
          edit.invalidate(); drawPrinting();
        }}));
      field("condition", "Condition (if known)"); field("language", "Language (if known)");
    } else {
      field("front", "Front face"); field("back", "Back face (blank if none)");
      field("set", "Set (if known)"); field("front_collector_number", "Front collector number");
      field("back_collector_number", "Back collector number"); field("finish", "Finish (if known)");
      field("front_details", "Front details", grid, true); field("back_details", "Back details", grid, true);
    }
    section.append(grid); field("notes", "Card notes", section, true);
    if (component.kind === "tokens") section.append(el("p", {class: "field-hint",
      text: "Details use semicolons, for example 1/1; green; flying. Keep unconfirmed characteristics explicit. Notes do not identify the token."}));
    section.append(el("div", {class: "actions"},
      el("button", {type: "button", class: "btn btn-quiet", text: component.kind === "cards" ? "Another printing…" : "Another row…",
        onclick: () => {
          if (!edit.available()) return;
          sync(); rows.splice(index + 1, 0, {...row, quantity: 1}); edit.invalidate(); draw();
        }}), el("button", {type: "button", class: "btn btn-quiet", text: "Remove row", "aria-label": `Remove row ${index + 1}`,
        disabled: !removable, "data-order-locked": removable ? "false" : "true",
        onclick: () => {
          if (!edit.available() || !removable) return;
          sync(); rows.splice(index, 1); edit.invalidate(); draw();
        }})));
    list.append(section);
    });
  }
  draw();
  edit.bind();
  return edit.sheet;
}

function shopOrderExtraSheet(order, component, view) {
  if (!shopMayEditOrder(view) || !shopQueueActive(view) || view.busy || view.stale || component.status !== "pending"
      || !["cards", "product"].includes(component.kind) || typeof component.extra_copies !== "boolean") return null;
  const undo = component.extra_copies, form = el("form", {class: "shop-order-form"});
  const edit = shopOrderChangeSheet(order, view, undo ? "Unmark additional copies" : "Confirm additional copies", form,
    () => ({action: "extra_copies", component: component.id, undo}));
  form.append(el("p", {text: `${shopOrderTitle(order)} · ${shopComponentWords(component)}`}),
    el("p", {text: undo ? "Remove the confirmation that this delivery contains additional physical copies. Deck Lab will again check whether these cards may already have been added to the collection."
      : "Confirm that this delivery contains additional physical copies, beyond copies already in the collection. Only confirm this when these are more cards, rather than the same cards already added to the collection."}),
    el("p", {class: "field-hint", text: "This changes how pending cards count as on the way. It does not receive the delivery or add cards to the collection. Review the affected deck tables before saving."}));
  edit.bind();
  return edit.sheet;
}

/** Quote stored product fields without trimming unknown details or list columns. */
function shopProductCSV(product) {
  const quote = value => {
    const text = String(value ?? "");
    return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  };
  return [product.columns, ...product.rows.map(row => product.columns.map(key => row[key]))]
    .map(row => row.map(quote).join(",")).join("\n");
}

function shopOrderProductSheet(order, component, view) {
  if (!shopMayEditOrder(view) || !shopQueueActive(view) || view.busy || view.stale || component.status !== "pending"
      || component.kind !== "product" || !component.edit_product) return null;
  const product = component.edit_product, inputs = {}, displayed = {};
  const form = el("form", {class: "shop-order-form"});
  const edit = shopOrderChangeSheet(order, view, "Correct product", form, () => {
    const values = Object.fromEntries(["name", "format", "status", "notes"]
      .filter(key => inputs[key].value !== displayed[key]).map(key => [key, inputs[key].value]));
    const body = {action: "product", component: component.id, values};
    if (inputs.csv.value !== displayed.csv) {
      if (!inputs.csv.value.trim()) throw new Error("Keep a complete product card list, including its basic lands.");
      body.csv = inputs.csv.value;
    }
    if (!Object.keys(values).length && !("csv" in body)) throw new Error("No product details have changed.");
    return body;
  });
  const field = (where, key, label, tag, value, props = {}, children = []) => {
    const input = el(tag, {id: `product-${key}-${edit.sheet.heading.id}`, "data-order-product-field": key, ...props}, children);
    input.value = value;
    inputs[key] = input; displayed[key] = input.value;
    where.append(el("label", {class: "field", for: input.id}, el("span", {text: label}), input));
  };
  form.append(el("p", {text: `${shopOrderTitle(order)} · ${shopComponentWords(component)}`}));
  const grid = el("div", {class: "shop-order-grid"});
  field(grid, "name", "Product name", "input", product.name || "", {type: "text", maxlength: 200});
  field(grid, "format", "Format (optional)", "input", product.format || "", {type: "text", maxlength: 200});
  field(grid, "status", "Status", "select", product.status, {},
    [el("option", {value: "ordered", text: "Ordered"}), el("option", {value: "preordered", text: "Preordered"})]);
  form.append(grid);
  field(form, "notes", "Product notes", "textarea", product.notes || "", {rows: 2, maxlength: 2000});
  field(form, "csv", "Product's complete card list (CSV)", "textarea", shopProductCSV(product), {rows: 8, maxlength: 1000000});
  form.append(el("p", {class: "field-hint", text: "Correct the whole published list, including basic lands. Keep section and deck columns for a product played as decks. Token cards are recorded after inspection on arrival."}),
    el("p", {class: "field-hint", text: "This changes the pending product. Review its resulting list and affected deck tables before saving."}));
  edit.bind();
  return edit.sheet;
}

/** Confirmation shows every resulting recorded field, including blank unknowns. */
function shopOrderComponentPreview(component) {
  const box = el("section", {}, el("h4", {text: `Component: ${component.id}`}));
  if (typeof component.extra_copies === "boolean") box.append(el("p", {text: component.extra_copies
    ? "Confirmed as additional physical copies beyond cards already in the collection."
    : "Not confirmed as additional copies; cards already in the collection will be checked."}));
  if (component.product) {
    const details = el("dl", {});
    for (const [key, label] of [["name", "Product name"], ["format", "Format"], ["status", "Status"], ["notes", "Product notes"]])
      details.append(el("dt", {text: label}), el("dd", {text: component.product[key] || "Not recorded"}));
    box.append(details);
  }
  const rows = component.product ? component.product.rows : component.rows;
  if (Array.isArray(rows)) for (const [index, row] of rows.entries()) {
    const details = el("dl", {});
    for (const [key, value] of Object.entries(row)) details.append(el("dt", {text: key.replace(/_/g, " ")}),
      el("dd", {text: value === "" || value === null || value === undefined ? "Not recorded" : String(value)}));
    box.append(el("h4", {text: `Row ${index + 1}`}), details);
  }
  return box;
}
