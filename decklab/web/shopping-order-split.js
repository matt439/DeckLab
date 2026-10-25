/* Split a pending shipment without receiving cards or changing its total.
 * Exact row details stay on both parts; arrival checks default to both. */
"use strict";

function shopOrderSplitSheet(order, component, view) {
  if (!shopMayEditOrder(view) || !shopQueueActive(view) || view.busy || view.stale || component.status !== "pending"
      || !["cards", "tokens"].includes(component.kind) || !Array.isArray(component.edit_rows) || !component.edit_rows.length) return null;
  const form = el("form", {class: "shop-order-form"}), quantities = [], checkChoices = [];
  const name = el("input", {type: "text", maxlength: 100, "data-order-split-field": "new_id", autocomplete: "off"});
  const total = component.edit_rows.reduce((sum, row) => sum + Number(row.quantity), 0);
  const edit = shopOrderChangeSheet(order, view, "Split shipment", form, () => {
    const new_id = name.value;
    if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(new_id))
      throw new Error("Name the new part using lowercase letters, numbers and single hyphens between words.");
    if ((order.components || []).some(part => part.id === new_id))
      throw new Error("That part name is already used in this order. Choose another name.");
    const take = [];
    quantities.forEach((input, index) => {
      const quantity = Number(input.value), have = Number(component.edit_rows[index].quantity);
      if (!/^\d+$/.test(input.value) || !Number.isSafeInteger(quantity) || quantity < 0 || quantity > have)
        throw new Error(`Row ${index + 1} needs a whole number from 0 to ${have} for the new part.`);
      if (quantity) take.push({row: index + 1, quantity});
    });
    const moved = take.reduce((sum, item) => sum + item.quantity, 0);
    if (!moved) throw new Error("Move at least one physical card to the new part.");
    if (moved >= total) throw new Error("Leave at least one physical card in the original part.");
    if (checkChoices.some(input => !["both", "original", "new"].includes(input.value)))
      throw new Error("Choose which part needs each arrival check.");
    return {action: "split", component: component.id, new_id, take,
      move_checks: checkChoices.flatMap((input, index) => input.value === "new" ? [index + 1] : []),
      keep_checks: checkChoices.flatMap((input, index) => input.value === "original" ? [index + 1] : [])};
  });
  form.append(el("p", {text: `${shopOrderTitle(order)} · Original part: ${component.id}`}),
    el("p", {class: "field-hint", text: "Choose how many physical cards from each row go into a separately arriving part. Both parts stay pending, with the same total cards and recorded details."}));
  name.id = `split-name-${edit.sheet.heading.id}`;
  form.append(el("label", {class: "field", for: name.id}, el("span", {text: "New part name"}), name),
    el("p", {class: "field-hint", text: "Use lowercase letters, numbers and single hyphens, for example second-parcel. The name must be unused in this order."}));
  if (component.extra_copies) form.append(el("p", {class: "note note-warn",
    text: "The original part is confirmed as additional physical copies. The new part will not have that confirmation and may need its own. Review any preview warnings before saving. After splitting, use Edit order… > Confirm additional copies… for the new part."}));
  component.edit_rows.forEach((row, index) => {
    const section = el("section", {class: "shop-order-section", "data-order-split-row": index}),
      title = row.name || [row.front, row.back].filter(Boolean).join(" // "),
      input = el("input", {type: "number", min: "0", max: String(row.quantity), step: "1", value: "0", inputMode: "numeric",
        id: `split-quantity-${edit.sheet.heading.id}-${index}`, "data-order-split-quantity": index});
    quantities.push(input);
    section.append(el("h3", {text: `${index + 1}. ${row.quantity} × ${title}`}), shopOrderSplitRowDetails(row, component.kind),
      el("label", {class: "field", for: input.id}, el("span", {text: `Physical cards to new part (0–${row.quantity})`}), input));
    form.append(section);
  });
  const checks = el("section", {class: "shop-order-section"}, el("h3", {text: "Checks on arrival"}));
  form.append(checks);
  for (const [index, text] of (component.checks || []).entries()) {
    const input = el("select", {id: `split-check-${edit.sheet.heading.id}-${index}`, "data-order-split-check": index},
      el("option", {value: "both", text: "Both parts"}), el("option", {value: "original", text: "Original part only"}),
      el("option", {value: "new", text: "New part only"}));
    input.value = "both"; checkChoices.push(input);
    checks.append(el("label", {class: "field", for: input.id}, el("span", {text: `${index + 1}. ${text}`}), input));
  }
  if (!checkChoices.length) checks.append(el("p", {class: "sub", text: "No arrival checks recorded."}));
  else checks.append(el("p", {class: "field-hint", text: "Each check applies to both parts unless you choose just one. A part cannot be received until its checks are verified."}));
  edit.bind();
  return edit.sheet;
}

function shopOrderSplitRowDetails(row, kind) {
  const fields = kind === "cards"
    ? [["set", "Set"], ["collector_number", "Collector number"], ["finish", "Finish"], ["condition", "Condition"], ["language", "Language"], ["notes", "Notes"]]
    : [["front", "Front face"], ["back", "Back face"], ["set", "Set"], ["front_collector_number", "Front collector number"],
      ["back_collector_number", "Back collector number"], ["finish", "Finish"], ["front_details", "Front details"], ["back_details", "Back details"], ["notes", "Notes"]];
  return el("dl", {class: "shop-order-row-details"}, fields.flatMap(([key, label]) => [el("dt", {text: label}),
    el("dd", {text: row[key] === "" || row[key] === null || row[key] === undefined ? "Not recorded" : String(row[key])})]));
}

function shopOrderSplitPreview(answer) {
  const box = el("div", {class: "shop-order-form"});
  for (const [index, component] of answer.components.entries()) {
    const section = el("section", {class: "shop-order-section"},
      el("h3", {text: index === 0 ? "Remaining in original part" : "New part"}), shopOrderComponentPreview(component));
    const checks = (answer.checks || []).find(part => part.component === component.id);
    section.append(el("h4", {text: `Checks on arrival: ${component.id}`}), checks && checks.checks.length
      ? el("ol", {}, checks.checks.map(text => el("li", {text}))) : el("p", {text: "No checks recorded."}));
    box.append(section);
  }
  return box;
}
